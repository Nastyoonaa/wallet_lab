package lab.wallet.network

import io.ktor.client.HttpClient
import io.ktor.client.HttpClientConfig
import io.ktor.client.plugins.HttpTimeout
import io.ktor.client.plugins.timeout
import io.ktor.client.request.get
import io.ktor.client.request.header
import io.ktor.client.request.post
import io.ktor.client.request.setBody
import io.ktor.client.statement.bodyAsText
import io.ktor.http.ContentType
import io.ktor.http.contentType
import io.ktor.http.isSuccess
import kotlinx.serialization.json.*

import lab.wallet.application.*

internal class KtorWalletApi(private val client: HttpClient, private val baseUrl: String) : WalletApi {
    override suspend fun wallets(): List<Wallet> = getList("wallets").map {
        val wallet = it.jsonObject
        Wallet(wallet.string("id"), wallet.string("name"), wallet.getValue("balance_kopecks").jsonPrimitive.long)
    }

    override suspend fun history(walletId: String): List<HistoryItem> = getList("wallets/$walletId/history").map {
        val entry = it.jsonObject
        HistoryItem(entry.transfer(), entry.getValue("signed_amount_kopecks").jsonPrimitive.long)
    }

    override suspend fun send(pending: PendingTransfer, demo: Boolean): TransferReply {
        val response = client.post("$baseUrl/transfers") {
            header("Idempotency-Key", pending.key)
            if (demo) header("X-Wallet-Lab-Timeout", "true")
            contentType(ContentType.Application.Json)
            setBody(buildJsonObject {
                put("sender_id", pending.sender)
                put("recipient_id", pending.recipient)
                put("amount_kopecks", pending.amount)
            }.toString())
        }
        val result = Json.parseToJsonElement(response.bodyAsText()).jsonObject
        if (response.status.value == 201) {
            val transfer = result.transfer()
            if (transfer.id.isNotBlank() && transfer.sender == pending.sender &&
                transfer.recipient == pending.recipient && transfer.amount == pending.amount
            ) {
                return TransferReply.Accepted(transfer)
            }
        }
        val reason = when (response.status.value to (result["detail"] as? JsonPrimitive)?.contentOrNull) {
            422 to "insufficient_funds" -> Rejection.InsufficientFunds
            422 to "same_wallet" -> Rejection.SameWallet
            404 to "wallet_not_found" -> Rejection.WalletNotFound
            else -> return TransferReply.Unknown
        }
        return TransferReply.Rejected(reason)
    }

    private suspend fun getList(path: String): JsonArray {
        val response = client.get("$baseUrl/$path") {
            timeout { requestTimeoutMillis = 8_000 }
        }
        check(response.status.isSuccess())
        return Json.parseToJsonElement(response.bodyAsText()).jsonArray
    }
}

private fun JsonObject.string(key: String) = getValue(key).jsonPrimitive.content

private fun JsonObject.transfer() = Transfer(
    string("id"), string("sender_id"), string("recipient_id"), getValue("amount_kopecks").jsonPrimitive.long,
)

internal fun HttpClientConfig<*>.configureWalletClient() {
    followRedirects = false
    install(HttpTimeout) {
        requestTimeoutMillis = 2_000
    }
}
