package lab.wallet.android

import android.app.Application
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import lab.wallet.AndroidWallet
import lab.wallet.ui.WalletScreen

class WalletViewModel(application: Application) : AndroidViewModel(application) {
    val wallet = AndroidWallet(application, viewModelScope)
    override fun onCleared() = wallet.close()
}

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val model = ViewModelProvider(this)[WalletViewModel::class.java]
        setContent { WalletScreen(model.wallet.controller) }
    }
}
