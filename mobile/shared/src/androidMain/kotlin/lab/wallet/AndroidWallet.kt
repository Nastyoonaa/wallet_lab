package lab.wallet

import lab.wallet.application.WalletController
import lab.wallet.network.KtorWalletApi
import lab.wallet.network.configureWalletClient
import lab.wallet.persistence.JsonPendingStore
import lab.wallet.persistence.PendingFile

import android.content.Context
import android.util.AtomicFile
import io.ktor.client.HttpClient
import io.ktor.client.engine.okhttp.OkHttp
import java.io.File
import java.io.FileNotFoundException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

class AndroidWallet(context: Context, scope: CoroutineScope) : AutoCloseable {
    private val client = HttpClient(OkHttp) { configureWalletClient() }
    val controller = WalletController(
        KtorWalletApi(client, "http://10.0.2.2:8000"),
        JsonPendingStore(AndroidPendingStore(File(context.filesDir, "pending-transfer.json"))),
        scope,
    )

    override fun close() = client.close()
}

private class AndroidPendingStore(private val path: File) : PendingFile {
    private val file = AtomicFile(path)

    override suspend fun read(): String? = withContext(Dispatchers.IO) {
        try {
            file.readFully().decodeToString(throwOnInvalidSequence = true)
        } catch (e: FileNotFoundException) {
            if (path.exists()) throw e
            null
        }
    }

    override suspend fun write(record: String) = withContext(Dispatchers.IO) {
        val stream = file.startWrite()
        try {
            stream.write(record.encodeToByteArray())
            file.finishWrite(stream)
        } catch (e: Exception) {
            file.failWrite(stream)
            throw e
        }
        check(file.readFully().contentEquals(record.encodeToByteArray()))
    }

    override suspend fun clear() = withContext(Dispatchers.IO) {
        file.delete()
        check(!path.exists())
    }
}
