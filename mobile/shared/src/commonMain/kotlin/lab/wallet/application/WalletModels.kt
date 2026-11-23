package lab.wallet.application

data class Wallet(val id: String, val name: String, val balance: Long)
data class Transfer(val id: String, val sender: String, val recipient: String, val amount: Long)
data class HistoryItem(val transfer: Transfer, val signedAmount: Long)
data class PendingTransfer(val key: String, val sender: String, val recipient: String, val amount: Long)

enum class Rejection {
    InsufficientFunds, SameWallet, WalletNotFound,
}

sealed interface TransferReply {
    data class Accepted(val transfer: Transfer) : TransferReply
    data class Rejected(val reason: Rejection) : TransferReply
    data object Unknown : TransferReply
}

interface WalletApi {
    suspend fun wallets(): List<Wallet>
    suspend fun history(walletId: String): List<HistoryItem>
    suspend fun send(pending: PendingTransfer, demo: Boolean): TransferReply
}

interface PendingStore {
    suspend fun read(): PendingTransfer?
    suspend fun write(record: PendingTransfer)
    suspend fun clear()
}

sealed interface TransferState {
    data object Idle : TransferState
    data class Sending(val request: PendingTransfer) : TransferState
    data class Unconfirmed(val request: PendingTransfer) : TransferState
    data class CleanupRequired(val request: PendingTransfer, val result: Resolved) : TransferState

    sealed interface Resolved : TransferState {
        data class Completed(val transferId: String) : Resolved
        data class Rejected(val reason: Rejection) : Resolved
    }
}
