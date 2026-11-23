# Wallet Lab

**English** · [Русский](README.ru.md)

Wallet Lab is a portfolio project about recovering a mobile money transfer after a network interruption or app restart. It simulates transfers in RUB between two seeded wallets. Alice starts with ₽1,000 and Bob with ₽250. All API amounts are integer kopecks.

The Android and iOS apps share a Kotlin Multiplatform module and a Compose Multiplatform screen. The FastAPI backend stores transfers in PostgreSQL.

## Quick start

With Docker Compose installed, run from the repository root:

```sh
docker compose up --build -d
curl -fsS http://localhost:8000/wallets
```

Open [the interactive API reference](http://localhost:8000/docs) for request and response schemas. The API container runs the versioned SQL migrations before it starts serving requests. Seeding runs once per database, so restarting Compose preserves balances and transfer history.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/wallets` | List wallets and balances |
| GET | `/wallets/{wallet_id}` | Read a wallet balance |
| GET | `/wallets/{wallet_id}/history` | Read newest transfers first, with signed amounts |
| POST | `/transfers` | Submit or replay a transfer using a UUID `Idempotency-Key` |

A successful submission or replay returns HTTP 201 and the original transfer body, including its ID and timestamp. Reusing the key with a different valid request body returns HTTP 409 with `idempotency_conflict`. Business rejections are also stable for a given key and body. If the user later chooses to attempt a new transfer, it gets a fresh key. Input-validation errors return HTTP 422 before any key is recorded.

## Run the mobile apps

Start the demo API from the repository root:

```sh
WALLET_LAB_DEMO=1 docker compose up --build -d
```

| Platform | Setup and launch |
| --- | --- |
| Android | Install JDK 17+ and Android SDK Platform 37. Open `mobile/` in Android Studio and run `androidApp` on an Android emulator. Or run `./gradlew :androidApp:installDebug` from `mobile/`, then open Wallet Lab. The emulator reaches the API at `10.0.2.2:8000`. |
| iOS | On an Apple Silicon Mac with Xcode, an iOS Simulator runtime, and JDK 17+, open `mobile/iosApp/WalletLab.xcodeproj`. Select the WalletLab scheme and an iPhone simulator, then run. The Xcode build calls the Gradle wrapper to build the shared framework. If Xcode cannot find Java, set `JAVA_HOME` in your shell and use the command below. The simulator reaches the API at `127.0.0.1:8000`. |

On macOS, the equivalent iOS build command from the repo root is:

```sh
xcodebuild -project mobile/iosApp/WalletLab.xcodeproj -scheme WalletLab \
  -configuration Debug -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath mobile/iosApp/DerivedData ARCHS=arm64 CODE_SIGNING_ALLOWED=NO build
```

Installation and launch with an already booted simulator:

```sh
xcrun simctl install booted mobile/iosApp/DerivedData/Build/Products/Debug-iphonesimulator/WalletLab.app
xcrun simctl launch booted lab.wallet.ios
```

## 60-second mobile recovery demo

1. Start with Alice at ₽1,000 and Bob at ₽250. Open Wallet Lab on Android and select Alice.
2. Enter `150` in **Сумма, ₽**, enable **Демо: потерять ответ** and tap **Перевести**. The API commits and delays its response for five seconds. The app times out after two seconds and shows **Не удалось подтвердить статус** (Could not confirm transfer status).
3. Force-stop and relaunch the app. For Android, run `adb shell am force-stop lab.wallet.android` and open Wallet Lab again. The saved transfer appears with the same amount and recipient.
4. Tap **Проверить статус**. The confirmation shows the original transfer ID. Alice has ₽850 and Bob has ₽400. Each wallet has one history item with that ID.

The amounts above assume a fresh database. To reset a disposable Compose demo, `docker compose down -v` deletes its database volume and all demo history. Start Compose again to reseed.

## HTTP recovery demo

Start with seeded balances and enable the server's post-commit delay:

```sh
WALLET_LAB_DEMO=1 docker compose up --build -d
```

Save the key and request body before the first attempt. The shell files stand in for the app's durable local storage.

```sh
pending=$(mktemp -d)
printf '%s\n' "$pending"
uuidgen > "$pending/key"
printf '%s\n' '{"sender_id":"alice","recipient_id":"bob","amount_kopecks":15000}' \
  > "$pending/transfer.json"

curl --max-time 1 -fsS http://localhost:8000/transfers \
  -H "Idempotency-Key: $(cat "$pending/key")" \
  -H 'X-Wallet-Lab-Timeout: true' -H 'Content-Type: application/json' \
  --data-binary "@$pending/transfer.json"
```

The first call times out. To stand in for a process restart, open a fresh terminal and set `pending` to the printed directory. Replay from disk:

```sh
curl --max-time 1 -fsS http://localhost:8000/transfers \
  -H "Idempotency-Key: $(cat "$pending/key")" \
  -H 'X-Wallet-Lab-Timeout: true' -H 'Content-Type: application/json' \
  --data-binary "@$pending/transfer.json"
curl -fsS http://localhost:8000/wallets
curl -fsS http://localhost:8000/wallets/alice/history
```

Alice has 85,000 kopecks, Bob has 40,000, and Alice's history contains one transfer with the ID returned by the replay. Replaying again returns the same body. The delay is off by default. When enabled it applies for five seconds only to the initial committed transfer with the demo header.

A timeout tells the client that it received no confirmation. The server may have committed the transfer before the connection closed. The mobile client shows “Could not confirm transfer status” and lets you retry the saved request with its original key. A fresh key represents a separate transfer.

## Disputed transfers and refunds

The sender can submit a dispute for a completed transfer. A demo operator must give a reason when approving or rejecting it. Approval only queues a payout. The separate execution request either posts a full reverse transfer or records that funds are still needed. The workflow is available in Swagger UI using test-role headers.

See the [roles, status transitions and API walkthrough](docs/disputes.md), the [BPMN diagram](docs/disputes.svg), and the [editable BPMN model](docs/disputes.bpmn).

## Architecture

The backend dependency direction is `api.py` / `disputes.py` → `services.py` → `domain.py`. The domain owns debit validation and the dispute and payout transitions. Services coordinate these rules through transaction-scoped storage ports. `postgres.py` implements those ports and maps SQL rows to domain values. The HTTP boundary maps inputs and responses and owns the explicit `with connect()` block. The simulated timeout runs after that transaction commits.

In `mobile/shared/src/commonMain`, `application` owns the models, the pending transfer flow and its `StateFlow`. The `network` and `persistence` adapters map HTTP and disk JSON to those models. The `ui` package renders the sealed transfer state and forwards actions to the controller. Android and iOS supply the HTTP engine and atomic file operations.

The app keeps one pending transfer as an atomically replaced JSON file in its private directory. Android uses `AtomicFile` and iOS uses Foundation's atomic file write. One small record fits this flow without a local relational database. It is written before the first POST and survives process death. After an ambiguous response, the app keeps the record and disables new transfers until it receives a definitive outcome. **Проверить статус** sends the original body and key without the demo-delay header. The app then clears the record and reloads the wallet and history after a definitive result.

FastAPI validates request inputs and delegates the write to PostgreSQL through Psycopg. Each transfer uses one Read Committed transaction:

1. Insert the idempotency key and request parameters into `transfer_requests`. Its primary key makes a concurrent duplicate wait for the first transaction. Once the first commits, a fresh SELECT can read the original parameters and resolve to the original transfer row or a stored business rejection.
2. Lock both wallet rows in ID order with `SELECT … FOR UPDATE`. For two different keys spending the same balance, the second transaction waits and then reads the updated balance. If the first debit leaves too little money, the second records an `insufficient_funds` rejection. Locking rows in a consistent order also protects concurrent transfers in opposite directions from deadlocking each other.
3. Insert the transfer and two signed ledger entries, update both balances, and commit. The transfer row linked by the key is the durable success result. Any unexpected database error rolls back all these writes together. The HTTP demo delay starts after commit and after the database connection closes.

See [PostgreSQL Read Committed semantics](https://www.postgresql.org/docs/17/transaction-iso.html) and [row-level locks](https://www.postgresql.org/docs/17/explicit-locking.html).

## Integration tests

Run the pure backend rules from `backend/` with `python -m pytest -q tests/test_domain.py`. They run without a database.

```sh
docker compose up -d --wait db
docker compose run --build --rm \
  -e TEST_DATABASE_URL=postgresql://wallet:wallet@db:5432/wallet \
  api python -m pytest -q
```

The suite creates and drops its own isolated schema per test. It starts a real HTTP server, checks persisted balances and ledger rows, and uses PostgreSQL lock observations to verify that concurrent requests overlap. To use a local PostgreSQL instance, install `backend/requirements-test.txt`, switch to `backend/`, and run `TEST_DATABASE_URL='postgresql://…' python -m pytest -q` with your own connection string. The test role needs permission to create schemas in that database.

From `mobile/`, run `./gradlew :shared:testAndroidHostTest` for the shared tests on the JVM and `./gradlew :shared:iosSimulatorArm64Test` for the same suite on iOS Simulator.

On an iPhone 18 Pro simulator (iOS 27.2), the app built, launched, loaded the wallet from the local API, and displayed a pre-seeded pending transfer after relaunch. The native shared tests covered replay and clearing the pending request. The complete tap-through demo was exercised on Android. Physical iOS devices were outside the validation scope.
