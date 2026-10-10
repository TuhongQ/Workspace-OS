package com.workspaceos.mobile

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import org.json.JSONArray
import org.json.JSONObject

data class NasEndpoint(
    val id: String = "default",
    val name: String = "家庭 NAS",
    val host: String = "192.168.1.9",
    val share: String = "Workspace",
    val username: String = "",
    val password: String = ""
) {
    val label: String get() = name.ifBlank { "$host/$share" }
    val ready: Boolean get() = host.isNotBlank() && share.isNotBlank()
}

data class WorkspaceSettings(
    val endpoints: List<NasEndpoint> = listOf(NasEndpoint()),
    val activeId: String = "default"
) {
    val active: NasEndpoint get() = endpoints.firstOrNull { it.id == activeId } ?: endpoints.first()
}

class SecureSettings(context: Context) {
    private val preferences = context.getSharedPreferences("workspace_os_secure", Context.MODE_PRIVATE)
    private val alias = "workspace_os_nas_password"

    fun load(): WorkspaceSettings {
        preferences.getString("endpoints", null)?.let { raw ->
            runCatching { parse(raw) }.getOrNull()?.let { return it }
        }
        // Migrate a single legacy connection into the first saved profile.
        val legacy = NasEndpoint(
            host = preferences.getString("host", "192.168.1.9") ?: "192.168.1.9",
            share = preferences.getString("share", "Workspace") ?: "Workspace",
            username = preferences.getString("username", "") ?: "",
            password = decrypt(preferences.getString("password", "").orEmpty())
        )
        val settings = WorkspaceSettings(listOf(legacy), legacy.id)
        save(settings)
        return settings
    }

    fun save(settings: WorkspaceSettings) {
        preferences.edit()
            .putString("endpoints", serialize(settings))
            .remove("password")
            .apply()
    }

    private fun serialize(settings: WorkspaceSettings): String {
        val array = JSONArray()
        settings.endpoints.forEach { endpoint ->
            array.put(
                JSONObject()
                    .put("id", endpoint.id)
                    .put("name", endpoint.name)
                    .put("host", endpoint.host)
                    .put("share", endpoint.share)
                    .put("username", endpoint.username)
                    .put("enc", encrypt(endpoint.password))
            )
        }
        return JSONObject().put("endpoints", array).put("activeId", settings.activeId).toString()
    }

    private fun parse(raw: String): WorkspaceSettings {
        val root = JSONObject(raw)
        val array = root.getJSONArray("endpoints")
        val endpoints = (0 until array.length()).map { index ->
            val item = array.getJSONObject(index)
            NasEndpoint(
                id = item.getString("id"),
                name = item.optString("name"),
                host = item.optString("host"),
                share = item.optString("share"),
                username = item.optString("username"),
                password = decrypt(item.optString("enc"))
            )
        }
        require(endpoints.isNotEmpty()) { "empty endpoints" }
        return WorkspaceSettings(endpoints, root.optString("activeId", endpoints.first().id))
    }

    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(alias, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").run {
            init(
                KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .build()
            )
            generateKey()
        }
    }

    private fun encrypt(value: String): String {
        if (value.isEmpty()) return ""
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key())
        return Base64.encodeToString(cipher.iv + cipher.doFinal(value.toByteArray(Charsets.UTF_8)), Base64.NO_WRAP)
    }

    private fun decrypt(value: String): String {
        if (value.isEmpty()) return ""
        return runCatching {
            val payload = Base64.decode(value, Base64.NO_WRAP)
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, payload.copyOfRange(0, 12)))
            String(cipher.doFinal(payload.copyOfRange(12, payload.size)), Charsets.UTF_8)
        }.getOrDefault("")
    }
}
