package lab.wallet

import lab.wallet.application.*
import lab.wallet.persistence.JsonPendingStore
import lab.wallet.persistence.PendingFile
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertIs
import kotlin.test.assertNull

class WalletControllerTest {
    @Test
    fun restoresUnknownTransferAndReusesExactlyTheSamePayload() = runBlocking {
        val file = MemoryFile()
        val store = JsonPendingStore(file)
        val api = FakeApi(store)
        val first = WalletController(api, store, this)
        first.idle()
        first.transfer("150,25", demo = true)
        val unknown = first.idle()
        val request = assertIs<TransferState.Unconfirmed>(unknown.transfer).request
        assertEquals(15025L, request.amount)
        assertNotNull(file.record)

        val restarted = WalletController(api, store, this)
        assertEquals(unknown.transfer, restarted.idle().transfer)
        assertEquals(1, api.calls.size)
        restarted.checkTransfer()
        val confirmed = restarted.idle()
        assertEquals(listOf(request to true, request to false), api.calls)
        assertEquals(TransferState.Resolved.Completed("sample-id"), confirmed.transfer)
        assertNull(file.record)
    }

    @Test
    fun restoresExistingFileAndClearsItOnlyAfterDefinitiveRejection() = runBlocking {
        val file = MemoryFile()
        file.record = """{"key":"existing-key","sender_id":"alice","recipient_id":"bob","amount_kopecks":15000}"""
        val store = JsonPendingStore(file)
        val api = FakeApi(store, TransferReply.Rejected(Rejection.InsufficientFunds))
        val controller = WalletController(api, store, this)
        val saved = PendingTransfer("existing-key", "alice", "bob", 15000)
        assertEquals(TransferState.Unconfirmed(saved), controller.idle().transfer)
        assertEquals(0, api.calls.size)

        controller.checkTransfer()
        assertEquals(TransferState.Resolved.Rejected(Rejection.InsufficientFunds), controller.idle().transfer)
        assertEquals(listOf(saved to false), api.calls)
        assertNull(file.record)
    }

    @Test
    fun storageFailurePreventsNetworkSubmission() = runBlocking {
        val store = JsonPendingStore(MemoryFile(failWrite = true))
        val api = FakeApi(store)
        val controller = WalletController(api, store, this)
        controller.idle()
        controller.transfer("150", demo = false)
        assertFalse(controller.idle().storageReady)
        assertEquals(0, api.calls.size)
    }

    @Test
    fun parsesRublesWithoutRoundingOrOverflow() {
        assertEquals(1L, parseRubles("0,01"))
        assertEquals(1250L, parseRubles("12.5"))
        assertEquals(Long.MAX_VALUE, parseRubles("92233720368547758.07"))
        for (invalid in listOf("0", "-1", "1.001", "92233720368547758.08", "1e2")) {
            assertNull(parseRubles(invalid))
        }
    }

    private suspend fun WalletController.idle() = withTimeout(3_000) {
        state.first { !it.busy }
    }

    private class MemoryFile(private val failWrite: Boolean = false) : PendingFile {
        var record: String? = null
        override suspend fun read() = record
        override suspend fun write(record: String) {
            check(!failWrite)
            this.record = record
        }

        override suspend fun clear() {
            record = null
        }
    }

    private class FakeApi(
        private val store: PendingStore,
        private val firstReply: TransferReply = TransferReply.Unknown,
    ) : WalletApi {
        val calls = mutableListOf<Pair<PendingTransfer, Boolean>>()
        override suspend fun wallets() = listOf(Wallet("alice", "Alice", 100000), Wallet("bob", "Bob", 25000))
        override suspend fun history(walletId: String) = emptyList<HistoryItem>()

        override suspend fun send(pending: PendingTransfer, demo: Boolean): TransferReply {
            assertEquals(pending, store.read())
            calls += pending to demo
            return if (calls.size == 1) firstReply else TransferReply.Accepted(
                Transfer("sample-id", pending.sender, pending.recipient, pending.amount),
            )
        }
    }
}
