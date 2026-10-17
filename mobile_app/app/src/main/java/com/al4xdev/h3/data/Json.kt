package com.al4xdev.h3.data

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.longOrNull

// Tree API only (no compiler plugin): numbers keep their JSON type, so seeds go out as integers
// and durations as decimals, which the strict backend DTOs require.
internal val JsonParser = Json { isLenient = false }

internal fun parseJson(text: String): JsonElement = JsonParser.parseToJsonElement(text)

internal fun JsonElement?.obj(): JsonObject? = this as? JsonObject
internal fun JsonElement?.arr(): JsonArray? = this as? JsonArray

internal fun JsonObject.str(key: String): String? =
    (this[key] as? JsonPrimitive)?.takeIf { it.isString }?.content

internal fun JsonObject.text(key: String, default: String = ""): String = str(key) ?: default
internal fun JsonObject.long(key: String): Long? = (this[key] as? JsonPrimitive)?.takeIf { !it.isString }?.longOrNull
internal fun JsonObject.int(key: String): Int? = (this[key] as? JsonPrimitive)?.takeIf { !it.isString }?.intOrNull
internal fun JsonObject.double(key: String): Double? = (this[key] as? JsonPrimitive)?.takeIf { !it.isString }?.doubleOrNull
internal fun JsonObject.bool(key: String): Boolean? = (this[key] as? JsonPrimitive)?.takeIf { !it.isString }?.booleanOrNull
internal fun JsonObject.objAt(key: String): JsonObject? = this[key] as? JsonObject
internal fun JsonObject.arrAt(key: String): List<JsonElement> = (this[key] as? JsonArray)?.toList() ?: emptyList()
internal fun JsonObject.strings(key: String): List<String> =
    arrAt(key).mapNotNull { (it as? JsonPrimitive)?.takeIf { p -> p.isString }?.content }

/** Server `error` fields are usually strings but may be objects; render them readably. */
internal fun JsonObject.errorText(key: String): String? = when (val v = this[key]) {
    null, JsonNull -> null
    is JsonPrimitive -> v.content
    else -> v.toString()
}

private val uuidPattern = Regex("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

/** The backend only accepts canonical lowercase 36-char UUIDs. */
fun isCanonicalUuid(value: String?): Boolean = value != null && uuidPattern.matches(value)

fun newUuid(): String = java.util.UUID.randomUUID().toString().lowercase()
