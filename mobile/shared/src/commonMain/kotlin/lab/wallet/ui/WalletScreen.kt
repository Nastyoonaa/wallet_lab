package lab.wallet.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import lab.wallet.application.*

@Composable
fun WalletScreen(controller: WalletController) {
    val state by controller.state.collectAsState()
    var amount by remember { mutableStateOf("") }
    var demo by remember { mutableStateOf(false) }
    val wallet = state.wallets.firstOrNull { it.id == state.selectedId }
    val recipient = state.wallets.singleOrNull { it.id != state.selectedId }
    val pending = state.transfer.pendingRequest()
    val focusManager = LocalFocusManager.current

    MaterialTheme(
        colorScheme = lightColorScheme(
            primary = Color(0xFF1E624F),
            primaryContainer = Color(0xFFD8EEE3),
            background = Color(0xFFF7F8F3),
            surface = Color(0xFFF7F8F3),
        ),
    ) {
        Surface(modifier = Modifier.fillMaxSize()) {
            LazyColumn(
                modifier = Modifier.fillMaxSize().safeDrawingPadding().imePadding(),
                contentPadding = PaddingValues(24.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                item {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("Wallet Lab", Modifier.weight(1f), style = MaterialTheme.typography.headlineMedium)
                        TextButton(onClick = controller::refresh, enabled = !state.busy) { Text("Обновить") }
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        state.wallets.forEach {
                            FilterChip(
                                selected = it.id == state.selectedId,
                                enabled = !state.busy,
                                onClick = { controller.select(it.id) },
                                label = { Text(it.name) },
                            )
                        }
                    }
                    wallet?.let {
                        Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer)) {
                            Column(Modifier.fillMaxWidth().padding(20.dp)) {
                                Text("Баланс", style = MaterialTheme.typography.labelLarge)
                                Text(formatRubles(it.balance), style = MaterialTheme.typography.displaySmall)
                            }
                        }
                    }
                }
                if (state.busy) item { LinearProgressIndicator(Modifier.fillMaxWidth()) }
                if (state.loadFailed) item {
                    Text("Не удалось обновить баланс и историю", color = MaterialTheme.colorScheme.error)
                }
                val message = when {
                    state.storageError == StorageError.Read -> "Не удалось прочитать сохранённый перевод. Обновите экран"
                    state.storageError == StorageError.Write -> "Не удалось сохранить перевод. Обновите экран"
                    state.inputError -> "Введите сумму больше нуля с точностью до копеек"
                    else -> state.transfer.message()
                }
                message?.let { item { Text(it, style = MaterialTheme.typography.bodyLarge) } }

                if (pending != null) {
                    item {
                        val senderName = state.wallets.firstOrNull { it.id == pending.sender }?.name ?: pending.sender
                        val recipientName = state.wallets.firstOrNull { it.id == pending.recipient }?.name ?: pending.recipient
                        Card {
                            Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                Text("$senderName → $recipientName · ${formatRubles(pending.amount)}")
                                Button(onClick = controller::checkTransfer, enabled = !state.busy) {
                                    Text("Проверить статус")
                                }
                            }
                        }
                    }
                } else if (wallet != null && recipient != null) {
                    item {
                        val canTransfer = !state.busy && state.storageReady
                        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            Text("Перевод → ${recipient.name}", style = MaterialTheme.typography.titleLarge)
                            OutlinedTextField(
                                value = amount,
                                onValueChange = { amount = it },
                                modifier = Modifier.fillMaxWidth(),
                                label = { Text("Сумма, ₽") },
                                singleLine = true,
                                enabled = canTransfer,
                                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                            )
                            Row(
                                modifier = Modifier.fillMaxWidth().toggleable(
                                    value = demo, enabled = canTransfer, role = Role.Switch,
                                    onValueChange = { demo = it },
                                ).padding(vertical = 6.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Switch(checked = demo, enabled = canTransfer, onCheckedChange = null)
                                Spacer(Modifier.width(10.dp))
                                Text("Демо: потерять ответ")
                            }
                            Button(
                                onClick = {
                                    focusManager.clearFocus()
                                    controller.transfer(amount, demo)
                                },
                                enabled = canTransfer && amount.isNotBlank(),
                            ) { Text("Перевести") }
                        }
                    }
                }

                if (wallet != null) {
                    item {
                        HorizontalDivider()
                        Spacer(Modifier.height(12.dp))
                        Text("История", style = MaterialTheme.typography.titleLarge)
                        if (state.history.isEmpty() && !state.busy && !state.loadFailed) {
                            Text("Переводов пока нет")
                        }
                    }
                    items(state.history, key = { it.transfer.id }) { entry ->
                        val debit = entry.signedAmount < 0
                        val peerId = if (debit) entry.transfer.recipient else entry.transfer.sender
                        val peer = state.wallets.firstOrNull { it.id == peerId }?.name ?: peerId
                        ListItem(
                            headlineContent = { Text(if (debit) "Перевод для $peer" else "Перевод от $peer") },
                            supportingContent = { Text(entry.transfer.id) },
                            trailingContent = {
                                Text((if (debit) "" else "+") + formatRubles(entry.signedAmount))
                            },
                        )
                    }
                }
            }
        }
    }
}

private fun formatRubles(amount: Long): String {
    val sign = if (amount < 0) "−" else ""
    val rubles = kotlin.math.abs(amount / 100)
    val kopecks = kotlin.math.abs(amount % 100).toString().padStart(2, '0')
    return "$sign$rubles,$kopecks ₽"
}

private fun TransferState.message(): String? = when (this) {
    TransferState.Idle, is TransferState.Sending -> null
    is TransferState.Unconfirmed -> "Не удалось подтвердить статус"
    is TransferState.Resolved.Completed -> "Перевод подтверждён · $transferId"
    is TransferState.Resolved.Rejected -> when (reason) {
        Rejection.InsufficientFunds -> "Недостаточно средств"
        Rejection.SameWallet -> "Выберите другой кошелёк"
        Rejection.WalletNotFound -> "Кошелёк не найден"
    }
    is TransferState.CleanupRequired ->
        "${result.message()}. Не удалось очистить сохранённый запрос. Проверьте статус ещё раз"
}
