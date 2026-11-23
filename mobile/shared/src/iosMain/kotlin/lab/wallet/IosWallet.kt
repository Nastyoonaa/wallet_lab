package lab.wallet

import lab.wallet.application.WalletController
import lab.wallet.network.KtorWalletApi
import lab.wallet.network.configureWalletClient
import lab.wallet.persistence.JsonPendingStore
import lab.wallet.persistence.PendingFile
import lab.wallet.ui.WalletScreen

import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.window.ComposeUIViewController
import io.ktor.client.HttpClient
import io.ktor.client.engine.darwin.Darwin
import kotlinx.cinterop.BetaInteropApi
import kotlinx.cinterop.ExperimentalForeignApi
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import platform.Foundation.NSFileManager
import platform.Foundation.NSHomeDirectory
import platform.Foundation.NSString
import platform.Foundation.NSUTF8StringEncoding
import platform.Foundation.create
import platform.Foundation.writeToFile
import platform.UIKit.UIViewController

fun walletViewController(): UIViewController = ComposeUIViewController {
    val scope = rememberCoroutineScope()
    val client = remember { HttpClient(Darwin) { configureWalletClient() } }
    val controller = remember {
        WalletController(KtorWalletApi(client, "http://127.0.0.1:8000"), JsonPendingStore(IosPendingStore()), scope)
    }
    DisposableEffect(client) { onDispose { client.close() } }
    WalletScreen(controller)
}

@OptIn(ExperimentalForeignApi::class, BetaInteropApi::class)
private class IosPendingStore : PendingFile {
    private val files = NSFileManager.defaultManager
    private val directory = "${NSHomeDirectory()}/Library/Application Support/WalletLab"
    private val path = "$directory/pending-transfer.json"

    override suspend fun read(): String? = withContext(Dispatchers.Default) {
        if (!files.fileExistsAtPath(path)) return@withContext null
        checkNotNull(NSString.create(contentsOfFile = path, encoding = NSUTF8StringEncoding, error = null))
            .toString()
    }

    override suspend fun write(record: String) = withContext(Dispatchers.Default) {
        check(files.createDirectoryAtPath(directory, withIntermediateDirectories = true, attributes = null, error = null))
        check(NSString.create(string = record).writeToFile(path, atomically = true, encoding = NSUTF8StringEncoding, error = null))
    }

    override suspend fun clear() = withContext(Dispatchers.Default) {
        if (files.fileExistsAtPath(path)) check(files.removeItemAtPath(path, error = null))
    }
}
