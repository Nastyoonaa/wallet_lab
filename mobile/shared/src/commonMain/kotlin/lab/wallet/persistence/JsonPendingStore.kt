package lab.wallet.persistence

import kotlinx.serialization.json.*
import lab.wallet.application.PendingStore
import lab.wallet.application.PendingTransfer

internal interface PendingFile {
    suspend fun read(): String?
    suspend fun write(record: String)
    suspend fun clear()
}

internal class JsonPendingStore(private val file: PendingFile) : PendingStore {
    override suspend fun read(): PendingTransfer? = file.read()?.let { record ->
        val json = Json.parseToJsonElement(record).jsonObject
        PendingTransfer(
            json.getValue("key").jsonPrimitive.content,
            json.getValue("sender_id").jsonPrimitive.content,
            json.getValue("recipient_id").jsonPrimitive.content,
            json.getValue("amount_kopecks").jsonPrimitive.long,
        ).also {
            require(it.amount > 0 && it.sender != it.recipient && it.key.isNotBlank())
        }
    }

    override suspend fun write(record: PendingTransfer) = file.write(
        buildJsonObject {
            put("key", record.key)
            put("sender_id", record.sender)
            put("recipient_id", record.recipient)
            put("amount_kopecks", record.amount)
        }.toString(),
    )

    override suspend fun clear() = file.clear()
}
