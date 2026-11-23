package lab.wallet.application

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlin.uuid.Uuid

data class WalletState(
    val wallets: List<Wallet> = emptyList(),
    val selectedId: String? = null,
    val history: List<HistoryItem> = emptyList(),
    val transfer: TransferState = TransferState.Idle,
    val inputError: Boolean = false,
    val storageError: StorageError? = null,
    val loadFailed: Boolean = false,
    val busy: Boolean = true,
    val storageReady: Boolean = false,
)

enum class StorageError { Read, Write }

class WalletController(
    private val api: WalletApi,
    private val store: PendingStore,
    private val scope: CoroutineScope,
) {
    private val mutableState = MutableStateFlow(WalletState())
    val state = mutableState.asStateFlow()

    init {
        scope.launch {
            try {
                restore()
                loadWallet()
            } finally {
                mutableState.update { it.copy(busy = false) }
            }
        }
    }

    fun refresh() = runAction {
        if (!state.value.storageReady) restore()
        loadWallet()
    }

    fun select(id: String) = runAction { loadWallet(id) }

    fun transfer(amountText: String, demo: Boolean) = runAction {
        val current = state.value
        if (!current.storageReady || current.transfer.pendingRequest() != null) return@runAction
        val sender = current.selectedId ?: return@runAction
        val recipient = current.wallets.singleOrNull { it.id != sender } ?: return@runAction
        val amount = parseRubles(amountText)
        if (amount == null) {
            mutableState.update { it.copy(inputError = true, transfer = TransferState.Idle) }
            return@runAction
        }
        val pending = PendingTransfer(Uuid.random().toString(), sender, recipient.id, amount)
        try {
            store.write(pending)
        } catch (e: CancellationException) {
            throw e
        } catch (_: Exception) {
            mutableState.update {
                it.copy(
                    storageReady = false,
                    storageError = StorageError.Write,
                    inputError = false,
                    transfer = TransferState.Idle,
                )
            }
            return@runAction
        }
        submit(pending, demo)
    }

    fun checkTransfer() = runAction {
        state.value.transfer.pendingRequest()?.let { submit(it, demo = false) }
    }

    private suspend fun restore() {
        try {
            val pending = store.read()
            mutableState.update {
                it.copy(
                    transfer = pending?.let { TransferState.Unconfirmed(it) } ?: TransferState.Idle,
                    storageReady = true,
                    storageError = null,
                )
            }
        } catch (e: CancellationException) {
            throw e
        } catch (_: Exception) {
            mutableState.update { it.copy(storageError = StorageError.Read) }
        }
    }

    private suspend fun submit(pending: PendingTransfer, demo: Boolean) {
        mutableState.update { it.copy(transfer = TransferState.Sending(pending), inputError = false) }
        val outcome = try {
            when (val result = api.send(pending, demo)) {
                is TransferReply.Accepted -> TransferState.Resolved.Completed(result.transfer.id)
                is TransferReply.Rejected -> TransferState.Resolved.Rejected(result.reason)
                TransferReply.Unknown -> null
            }
        } catch (e: CancellationException) {
            throw e
        } catch (_: Exception) {
            null
        }
        if (outcome == null) {
            mutableState.update { it.copy(transfer = TransferState.Unconfirmed(pending)) }
            return
        }
        try {
            store.clear()
            mutableState.update { it.copy(transfer = outcome) }
        } catch (e: CancellationException) {
            throw e
        } catch (_: Exception) {
            mutableState.update { it.copy(transfer = TransferState.CleanupRequired(pending, outcome)) }
        }
        loadWallet()
    }

    private suspend fun loadWallet(preferredId: String? = state.value.selectedId) {
        val selected = preferredId ?: state.value.transfer.pendingRequest()?.sender
        mutableState.update {
            it.copy(selectedId = selected, history = if (selected == it.selectedId) it.history else emptyList())
        }
        try {
            val wallets = api.wallets()
            val id = wallets.firstOrNull { it.id == selected }?.id ?: wallets.firstOrNull()?.id
            mutableState.update { it.copy(wallets = wallets, selectedId = id) }
            val history = if (id == null) emptyList() else api.history(id)
            mutableState.update { it.copy(history = history, loadFailed = false) }
        } catch (e: CancellationException) {
            throw e
        } catch (_: Exception) {
            mutableState.update { it.copy(loadFailed = true) }
        }
    }

    // The UI and these entry points run on the main dispatcher.
    private fun runAction(block: suspend () -> Unit) {
        if (state.value.busy) return
        mutableState.update { it.copy(busy = true) }
        scope.launch {
            try {
                block()
            } finally {
                mutableState.update { it.copy(busy = false) }
            }
        }
    }

}

internal fun TransferState.pendingRequest(): PendingTransfer? = when (this) {
    is TransferState.Sending -> request
    is TransferState.Unconfirmed -> request
    is TransferState.CleanupRequired -> request
    TransferState.Idle, is TransferState.Resolved -> null
}

internal fun parseRubles(input: String): Long? {
    val match = Regex("([0-9]+)(?:[,.]([0-9]{1,2}))?").matchEntire(input.trim()) ?: return null
    val rubles = match.groupValues[1].toLongOrNull() ?: return null
    val kopecks = match.groupValues[2].padEnd(2, '0').toLong()
    if (rubles > (Long.MAX_VALUE - kopecks) / 100) return null
    return (rubles * 100 + kopecks).takeIf { it > 0 }
}
