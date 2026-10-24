package com.al4xdev.h3.ui

import android.app.Application
import android.net.Uri
import android.provider.OpenableColumns
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.viewModelScope
import com.al4xdev.h3.H3App
import com.al4xdev.h3.data.ApiClient
import com.al4xdev.h3.data.ApiResult
import com.al4xdev.h3.data.Assembly
import com.al4xdev.h3.data.BatchRecord
import com.al4xdev.h3.data.Block
import com.al4xdev.h3.data.BlockState
import com.al4xdev.h3.data.Candidate
import com.al4xdev.h3.data.Drafts
import com.al4xdev.h3.data.Durations
import com.al4xdev.h3.data.EditRecord
import com.al4xdev.h3.data.EditorConfig
import com.al4xdev.h3.data.EventStream
import com.al4xdev.h3.data.InputItem
import com.al4xdev.h3.data.InsertDraft
import com.al4xdev.h3.data.MAX_BLOCKS
import com.al4xdev.h3.data.NewRoteiroDraft
import com.al4xdev.h3.data.NextAction
import com.al4xdev.h3.data.OpKind
import com.al4xdev.h3.data.PendingOp
import com.al4xdev.h3.data.PendingOps
import com.al4xdev.h3.data.Roteiro
import com.al4xdev.h3.data.RoteiroLogic
import com.al4xdev.h3.data.RunStates
import com.al4xdev.h3.data.SegmentRecord
import com.al4xdev.h3.data.Settings
import com.al4xdev.h3.data.SharedPrefsStore
import com.al4xdev.h3.data.SummaryItem
import com.al4xdev.h3.data.newUuid
import com.al4xdev.h3.data.outcome
import com.al4xdev.h3.data.str
import com.al4xdev.h3.data.strings
import com.al4xdev.h3.service.VideoDownloadWorker
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

/** Last known value of a remote read, plus whether a read is in flight and its last error. */
data class Remote<T>(val value: T? = null, val loading: Boolean = false, val error: String? = null)

/**
 * Single state holder. Rules it enforces:
 *  - navigation changes only from user/event callbacks, never during composition;
 *  - every POST with a client ID is recorded on disk first; an uncertain answer only enables
 *    "Consultar" (GET of the same ID), never an automatic re-POST;
 *  - updates come from SSE while visible (and FCM in background), no polling.
 */
class AppViewModel(app: Application, private val handle: SavedStateHandle) : AndroidViewModel(app) {
    private val ctx: Application get() = getApplication()
    val settings = Settings(app)
    val api = ApiClient { settings.baseUrl }
    private val pendingStore = PendingOps(SharedPrefsStore(app, "h3_pending", durable = true))
    private val drafts = Drafts(SharedPrefsStore(app, "h3_drafts", durable = false))
    private val events = EventStream(api)

    // ---------------- navigation ----------------

    var nav by mutableStateOf(NavStack(Nav.decode(handle.get<String>(NAV_KEY)), Nav.decodeList(handle.get<String>(FORWARD_KEY))))
        private set
    val stack: List<Screen> get() = nav.back
    val top: Screen get() = nav.top

    private fun updateNav(value: NavStack) {
        nav = value
        handle[NAV_KEY] = Nav.encode(value.back)
        handle[FORWARD_KEY] = Nav.encode(value.forward)
    }

    fun push(screen: Screen) = updateNav(nav.push(screen))

    fun back(): Boolean {
        if (!nav.canPop) return false
        updateNav(nav.pop())
        if (top == Screen.Library) loadLibrary()
        return true
    }

    /** Forward swipe: re-push the most recently popped screen with its saved state. */
    fun forward() = updateNav(nav.goForward())

    fun replaceTop(screen: Screen) = updateNav(nav.replaceTop(screen))

    /** Pops only if the user is still on `screen` when an async action finishes. */
    private fun leave(screen: Screen) {
        if (top == screen) back()
    }

    private fun resetTo(vararg screens: Screen) = updateNav(nav.reset(*screens))

    // ---------------- feedback ----------------

    var notice by mutableStateOf<String?>(null)
        private set

    fun say(text: String) { notice = text }
    fun clearNotice() { notice = null }

    /** Raw text of an invalid Grok answer, shown in a dialog so the user sees what came back. */
    var invalidAnswer by mutableStateOf<String?>(null)
        private set

    fun dismissInvalid() { invalidAnswer = null }

    // ---------------- busy flags ----------------

    private val busy = mutableStateMapOf<String, Boolean>()
    fun isBusy(key: String): Boolean = busy[key] == true

    private fun op(key: String, block: suspend CoroutineScope.() -> Unit) {
        if (busy[key] == true) return
        busy[key] = true
        viewModelScope.launch {
            try { block() } finally { busy.remove(key) }
        }
    }

    // ---------------- pending (uncertain) requests ----------------

    private var pendingTick by mutableIntStateOf(0)

    fun pendingFor(roteiroId: String): List<PendingOp> {
        pendingTick
        return pendingStore.forRoteiro(roteiroId)
    }

    private fun begin(op: PendingOp): PendingOp = pendingStore.begin(op).also { pendingTick++ }
    private fun settle(op: PendingOp, result: ApiResult<*>) {
        pendingStore.settle(op, result.outcome(), result.message()); pendingTick++
    }
    private fun resolve(id: String) { pendingStore.resolve(id); pendingTick++ }

    // ---------------- remote state ----------------

    var library by mutableStateOf(Remote<List<SummaryItem>>())
        private set
    var favorites by mutableStateOf<Set<String>>(emptySet())
        private set
    var batch by mutableStateOf<BatchRecord?>(null)
        private set
    val docs = mutableStateMapOf<String, Remote<Roteiro>>()
    var assemblies by mutableStateOf(Remote<List<Assembly>>())
        private set
    val segments = mutableStateMapOf<String, SegmentRecord>()
    val edits = mutableStateMapOf<String, Remote<EditRecord>>()
    val editors = mutableStateMapOf<String, Remote<EditorConfig>>()
    var inputs by mutableStateOf(Remote<List<InputItem>>())
        private set
    var inputsTotal by mutableIntStateOf(0)
        private set
    var live by mutableStateOf(false)
        private set

    fun doc(id: String): Roteiro? = docs[id]?.value

    /** Active batch on this roteiro fences generation, decisions and edits there. */
    fun batchOn(roteiroId: String): BatchRecord? = batch?.takeIf { it.active && it.roteiroId == roteiroId }

    fun uncertainBlocks(roteiroId: String): Set<String> =
        pendingFor(roteiroId).filter { it.kind == OpKind.ATTEMPT }.mapNotNull { it.blockId }.toSet()

    fun nextAction(doc: Roteiro): NextAction = RoteiroLogic.nextAction(doc, uncertainBlocks(doc.id))

    // ---------------- loading ----------------

    fun loadLibrary() = viewModelScope.launch {
        library = library.copy(loading = true)
        coroutineScope {
            val favs = async { api.favorites() }
            val current = async { api.currentBatch() }
            val summary = fetchSummary()
            library = if (summary is ApiResult.Ok) Remote(summary.value) else Remote(library.value, false, summary.message())
            favs.await().valueOrNull()?.let { favorites = it }
            current.await().let { if (it is ApiResult.Ok) batch = it.value }
        }
    }

    /** `/roteiros/summary`; falls back to the full list on a backend that predates it (404). */
    private suspend fun fetchSummary(): ApiResult<List<SummaryItem>> {
        val summary = api.summary()
        if (summary !is ApiResult.Http || summary.code != 404) return summary
        return api.roteiros().map { list ->
            list.map { d ->
                val states = RoteiroLogic.states(d).map { if (it == BlockState.UNCERTAIN) BlockState.ACTIVE else it }
                SummaryItem(d.id, d.name, d.idea, d.adopted, d.revision, d.blocks.size,
                    states.groupingBy { it.wire }.eachCount(), states.map { it.wire }, null)
            }
        }
    }

    fun loadBatch() = viewModelScope.launch {
        val r = api.currentBatch()
        if (r is ApiResult.Ok) batch = r.value
    }

    fun ensureRoteiro(id: String) {
        val current = docs[id]
        if (current?.value == null && current?.loading != true) loadRoteiro(id)
    }

    fun loadRoteiro(id: String) = viewModelScope.launch { reloadRoteiro(id) }

    private suspend fun reloadRoteiro(id: String): Roteiro? {
        val previous = docs[id]
        docs[id] = (previous ?: Remote()).copy(loading = true)
        return when (val r = api.roteiro(id)) {
            is ApiResult.Ok -> {
                // A read started before our own PUT/POST may land after it: never go back in revision.
                val newer = docs[id]?.value?.takeIf { it.revision > r.value.revision }
                docs[id] = Remote(newer ?: r.value)
                newer ?: r.value
            }
            else -> { docs[id] = Remote(previous?.value, false, r.message()); null }
        }
    }

    private fun store(doc: Roteiro) {
        val current = docs[doc.id]?.value
        if (current == null || current.revision <= doc.revision) docs[doc.id] = Remote(doc)
    }

    // ---------------- live updates (SSE in foreground) ----------------

    private var sseJob: Job? = null
    private var refreshJob: Job? = null
    private val dirty = mutableSetOf<String>()

    fun onForeground() {
        if (sseJob?.isActive == true) return
        refreshVisible(setOf(".data"))
        sseJob = viewModelScope.launch {
            var wait = 1_000L
            var first = true
            while (isActive) {
                try {
                    events.listen(
                        onOpen = {
                            viewModelScope.launch {
                                live = true
                                wait = 1_000L
                                // Changes made while disconnected are picked up by one re-read.
                                if (!first) refreshVisible(setOf(".data"))
                                first = false
                            }
                        },
                        onPath = { path -> viewModelScope.launch { queueRefresh(path) } },
                    )
                } catch (e: CancellationException) {
                    throw e
                } catch (_: Exception) {
                }
                live = false
                // Reconnect backoff for the event stream; data itself is never polled.
                delay(wait)
                wait = (wait * 2).coerceAtMost(30_000L)
            }
        }
    }

    fun onBackground() {
        sseJob?.cancel()
        sseJob = null
        live = false
    }

    private fun queueRefresh(path: String) {
        dirty += path
        if (refreshJob?.isActive == true) return
        refreshJob = viewModelScope.launch {
            delay(300) // coalesce bursts of manifest writes into one re-read
            val paths = dirty.toSet()
            dirty.clear()
            refreshVisible(paths)
        }
    }

    private fun refreshVisible(paths: Set<String>) {
        val all = ".data" in paths
        fun touches(prefix: String) = all || paths.any { it.startsWith(prefix) }
        val runsChanged = touches("runs/")
        if (all || touches("roteiro-batches") || runsChanged) loadBatch()
        if (top == Screen.Library && (all || touches("roteiros") || runsChanged || touches("library"))) loadLibrary()
        val visible = stack.mapNotNull { it.ownerId }.toSet()
        for (id in visible) {
            if (all || runsChanged || touches("roteiro-batches") || paths.any { it.contains(id) }) loadRoteiro(id)
        }
        stack.filterIsInstance<Screen.Redo>().forEach { s ->
            val id = edits[s.roteiroId + ":" + s.blockId]?.value?.id
            if (id != null && (all || runsChanged || paths.any { it.contains(s.roteiroId) })) loadEdit(s.roteiroId, s.blockId, id)
        }
        if (stack.any { it is Screen.Assembly } && touches("assemblies")) loadAssemblies()
    }

    // ---------------- notification entry ----------------

    fun openFromNotification(runId: String?, roteiroId: String?) {
        if (roteiroId != null) { resetTo(Screen.Roteiro(roteiroId)); return }
        runId ?: return
        viewModelScope.launch {
            val known = docs.values.mapNotNull { it.value }.firstOrNull { d -> d.attempts.any { it.runId == runId } }
            val doc = known ?: api.roteiros().valueOrNull()?.firstOrNull { d -> d.attempts.any { it.runId == runId } }
            if (doc == null) {
                say("Video ${runId.take(8)} is not in any script.")
                return@launch
            }
            store(doc)
            val attempt = doc.attempts.first { it.runId == runId }
            resetTo(Screen.Roteiro(doc.id), Screen.Block(doc.id, attempt.blockId))
        }
    }

    // ---------------- library actions ----------------

    fun setFavorite(id: String, favorite: Boolean) = op("fav:$id") {
        val r = api.setFavorite(id, favorite)
        if (r is ApiResult.Ok) favorites = if (favorite) favorites + id else favorites - id else say(r.message())
    }

    fun deleteRoteiro(item: SummaryItem) = op("delete:${item.id}") {
        when (val r = api.deleteRoteiro(item.id, item.revision)) {
            is ApiResult.Ok -> { docs.remove(item.id); drafts.clearCandidate(item.id); say("Script deleted. Media moved to PC trash.") }
            else -> say(r.message())
        }
        loadLibrary()
    }

    fun stopBatch(b: BatchRecord) = op("stopbatch:${b.id}") {
        when (val r = api.stopBatch(b.roteiroId, b.id)) {
            is ApiResult.Ok -> { batch = r.value; say("Stop requested for batch.") }
            else -> { say(r.message()); loadBatch() }
        }
        reloadRoteiro(b.roteiroId)
    }

    // ---------------- T1 new roteiro ----------------

    var newDraft by mutableStateOf(drafts.newRoteiro())
        private set

    fun updateNewDraft(d: NewRoteiroDraft, durable: Boolean = false) {
        newDraft = d
        drafts.saveNewRoteiro(d, durable)
    }

    fun loadInputs(more: Boolean = false) = op("inputs") {
        val offset = if (more) inputs.value?.size ?: 0 else 0
        inputs = inputs.copy(loading = true, error = null)
        when (val r = api.inputs(offset)) {
            is ApiResult.Ok -> {
                inputs = Remote((if (more) inputs.value.orEmpty() else emptyList()) + r.value.first)
                inputsTotal = r.value.second
            }
            else -> inputs = Remote(inputs.value, false, r.message())
        }
    }

    fun upload(uri: Uri) = op("upload") {
        val resolver = ctx.contentResolver
        val mime = resolver.getType(uri)
        if (mime != "image/png" && mime != "image/jpeg") {
            say("Please use a PNG or JPEG photo (Grok refuses other formats).")
            return@op
        }
        var name = "phone photo"
        var size = -1L
        resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use { c ->
            if (c.moveToFirst()) {
                name = c.getString(0)?.take(200) ?: name
                size = if (c.isNull(1)) -1 else c.getLong(1)
            }
        }
        if (size > MAX_UPLOAD) { say("Photo exceeds 20 MiB, Grok's limit."); return@op }
        val bytes = withContext(Dispatchers.IO) {
            resolver.openInputStream(uri)?.use { input ->
                val buffer = input.readNBytes(MAX_UPLOAD.toInt() + 1)
                buffer.takeIf { it.size <= MAX_UPLOAD }
            }
        }
        if (bytes == null || bytes.isEmpty()) { say("Could not read photo (empty or above 20 MiB)."); return@op }
        val png = bytes.size > 8 && bytes[0] == 0x89.toByte() && bytes[1] == 'P'.code.toByte()
        val jpeg = bytes.size > 3 && bytes[0] == 0xFF.toByte() && bytes[1] == 0xD8.toByte()
        if (!png && !jpeg) { say("Content is neither PNG nor JPEG."); return@op }
        when (val r = api.upload(name, bytes, mime)) {
            is ApiResult.Ok -> {
                updateNewDraft(newDraft.copy(reference = r.value))
                say("Photo uploaded to PC.")
                loadInputs()
            }
            else -> say(r.message())
        }
    }

    private fun validNew(d: NewRoteiroDraft): Pair<Double, Long>? {
        val duration = Durations.parse(d.durationText)
        val seed = Durations.parseSeed(d.seedText)
        when {
            d.reference == null -> say("Choose the reference photo.")
            d.idea.isBlank() -> say("Write the idea.")
            d.title.length > 256 -> say("Title has more than 256 characters.")
            duration == null -> say("Invalid duration.")
            seed == null -> say("Invalid seed.")
            else -> return duration.toDouble() to seed
        }
        return null
    }

    /** Creates the roteiro at most once per draft; a retry reuses (and updates) the same one. */
    private suspend fun ensureCreated(d: NewRoteiroDraft): Roteiro? {
        val ref = d.reference?.reference ?: return null
        d.roteiroId?.let { id ->
            val doc = reloadRoteiro(id) ?: run { say(docs[id]?.error ?: "Could not read script."); return null }
            if (doc.adopted || doc.attempts.isNotEmpty()) {
                finishNew(id)
                say("This script was already adopted; opening.")
                return null
            }
            if (doc.name != d.title.trim() || doc.idea != d.idea || doc.reference != ref) {
                return when (val r = api.putRoteiro(doc, doc.blocks, adopted = false, name = d.title.trim(), idea = d.idea, reference = ref)) {
                    is ApiResult.Ok -> r.value.also(::store)
                    else -> { say(r.message()); null }
                }
            }
            return doc
        }
        if (d.creationUncertain) {
            say("Previous creation had no response. Tap “Find on PC” before creating another.")
            return null
        }
        // POST /roteiros has no client ID: mark the draft first so a crash or timeout is visible.
        updateNewDraft(d.copy(creationUncertain = true), durable = true)
        val r = api.createRoteiro(d.title.trim(), d.idea, ref)
        return when {
            r is ApiResult.Ok -> {
                updateNewDraft(newDraft.copy(roteiroId = r.value.id, creationUncertain = false), durable = true)
                store(r.value)
                r.value
            }
            r.uncertain -> { say("No response from PC when creating script. Tap “Find on PC”."); null }
            else -> { updateNewDraft(newDraft.copy(creationUncertain = false)); say(r.message()); null }
        }
    }

    private fun finishNew(roteiroId: String) {
        updateNewDraft(NewRoteiroDraft())
        if (top == Screen.NewRoteiro) replaceTop(Screen.Roteiro(roteiroId))
    }

    fun proposeNew() = op("new:create") {
        val d = newDraft
        val (duration, seed) = validNew(d) ?: return@op
        val doc = ensureCreated(d) ?: return@op
        if (propose(doc, d.count, duration, seed)) finishNew(doc.id)
    }

    fun writeNewByHand() = op("new:create") {
        val d = newDraft
        val (duration, seed) = validNew(d) ?: return@op
        val doc = ensureCreated(d) ?: return@op
        saveCandidate(doc.id, Candidate(d.title.trim(), RoteiroLogic.manualBlocks(d.count, d.idea, duration, seed), fromGrok = false))
        finishNew(doc.id)
    }

    fun findCreatedRoteiro() = op("new:find") {
        val d = newDraft
        when (val r = fetchSummary()) {
            is ApiResult.Ok -> {
                val match = r.value.filter { !it.adopted && it.blockCount == 0 && it.idea == d.idea && it.name == d.title.trim() }
                    .maxByOrNull { it.updatedAt.orEmpty() }
                if (match == null) {
                    updateNewDraft(d.copy(creationUncertain = false), durable = true)
                    say("The PC did not register this script. You can create it.")
                } else {
                    updateNewDraft(d.copy(roteiroId = match.id, creationUncertain = false), durable = true)
                    say("Script found on PC; it will be reused.")
                }
            }
            else -> say(r.message())
        }
    }

    /** Grok proposal; the candidate stays on the phone until "Usar este roteiro". */
    private suspend fun propose(doc: Roteiro, count: Int, duration: Double, seed: Long): Boolean {
        val r = api.proposal(doc.id, doc.revision, count, duration, seed)
        when {
            r is ApiResult.Ok -> {
                saveCandidate(doc.id, Candidate(r.value.name, r.value.blocks, fromGrok = true, stale = r.value.stale,
                    scenes = r.value.scenes, vision = r.value.vision))
                return true
            }
            r is ApiResult.Http && r.code == 422 && r.body != null && ("raw_text" in r.body || "raw_texts" in r.body) -> {
                val raw = r.body.strings("raw_texts").filter { it.isNotBlank() }.ifEmpty { listOfNotNull(r.body.str("raw_text")) }
                invalidAnswer = (listOf(r.detail) + raw).joinToString("\n\n")
                say("Grok returned an invalid proposal; your idea was kept.")
            }
            r.uncertain -> say("No response from Grok/PC (${r.message()}). Tapping again reuses the same script.")
            else -> say(r.message())
        }
        return false
    }

    // ---------------- candidate (proposal not adopted) ----------------

    private var draftTick by mutableIntStateOf(0)
    private val candidateCache = HashMap<String, Candidate?>()

    fun candidate(roteiroId: String): Candidate? {
        draftTick
        return candidateCache.getOrPut(roteiroId) { drafts.candidate(roteiroId) }
    }

    fun saveCandidate(roteiroId: String, c: Candidate?) {
        if (c == null) drafts.clearCandidate(roteiroId) else drafts.saveCandidate(roteiroId, c)
        candidateCache[roteiroId] = c
        draftTick++
    }

    fun reproposal(roteiroId: String, count: Int, durationText: String, seedText: String) = op("propose:$roteiroId") {
        val duration = Durations.parse(durationText)?.toDouble() ?: run { say("Invalid duration."); return@op }
        val seed = Durations.parseSeed(seedText) ?: run { say("Invalid seed."); return@op }
        val doc = reloadRoteiro(roteiroId) ?: return@op
        propose(doc, count, duration, seed)
    }

    fun manualCandidate(roteiroId: String, count: Int, durationText: String, seedText: String) {
        val doc = doc(roteiroId) ?: return
        val duration = Durations.parse(durationText)?.toDouble() ?: run { say("Invalid duration."); return }
        val seed = Durations.parseSeed(seedText) ?: run { say("Invalid seed."); return }
        saveCandidate(roteiroId, Candidate(doc.name, RoteiroLogic.manualBlocks(count, doc.idea, duration, seed), fromGrok = false))
    }

    fun adoptCandidate(roteiroId: String) = op("adopt:$roteiroId") {
        val doc = doc(roteiroId) ?: return@op
        val c = candidate(roteiroId) ?: return@op
        val r = api.putRoteiro(doc, c.blocks, adopted = true, name = doc.name.ifBlank { c.name.take(256) })
        when {
            r is ApiResult.Ok -> { store(r.value); saveCandidate(roteiroId, null); say("Script adopted. Ready to generate.") }
            r.uncertain -> {
                val fresh = reloadRoteiro(roteiroId)
                if (fresh?.adopted == true && fresh.blocks.map { it.id } == c.blocks.map { it.id }) {
                    saveCandidate(roteiroId, null); say("Script adopted.")
                } else say("Uncertain response; re-read from PC: not yet adopted. The proposal remains here.")
            }
            else -> { say(r.message()); reloadRoteiro(roteiroId) }
        }
    }

    // ---------------- batch ----------------

    fun startBatch(roteiroId: String) = op("batch:$roteiroId") {
        if (pendingStore.find(OpKind.BATCH, roteiroId) != null) { say("There is an unconfirmed batch; check it first."); return@op }
        val doc = reloadRoteiro(roteiroId) ?: return@op
        val p = begin(PendingOp(OpKind.BATCH, newUuid(), roteiroId))
        val r = api.startBatch(roteiroId, p.id, doc.revision)
        settle(p, r)
        when {
            r is ApiResult.Ok -> { batch = r.value; say("Batch started on PC.") }
            r.uncertain -> say("Uncertain response. Check the same batch; do not tap Generate again.")
            else -> say(r.message())
        }
        reloadRoteiro(roteiroId)
    }

    /** The POST that created this record is still waiting for its answer in this process. */
    fun inFlight(p: PendingOp): Boolean = when (p.kind) {
        OpKind.BATCH -> isBusy("batch:${p.roteiroId}")
        OpKind.SEGMENT -> isBusy("segment:${p.roteiroId}")
        OpKind.ASSEMBLY -> isBusy("assemble:${p.roteiroId}")
        OpKind.ATTEMPT -> isBusy("attempt:${p.roteiroId}")
        OpKind.EDIT -> isBusy("redo:${p.blockId}")
        OpKind.DECISION -> isBusy("decide:${p.id}")
    }

    /** GET of the same ID for any uncertain request. Never re-POSTs. */
    fun consult(p: PendingOp) = op("consult:${p.id}") {
        // A read racing its own POST could see 404 and drop a record that is about to exist.
        if (inFlight(p)) return@op
        when (p.kind) {
            OpKind.BATCH -> {
                val rid = p.roteiroId ?: return@op
                when (val r = api.batch(rid, p.id)) {
                    is ApiResult.Ok -> { resolve(p.id); batch = r.value.takeIf { it.active } ?: batch; say("Batch found: ${r.value.describe()}") }
                    is ApiResult.Http -> if (r.code == 404) { resolve(p.id); say("The PC did not register this batch. You can generate again.") } else say(r.message())
                    else -> say(r.message())
                }
            }
            OpKind.SEGMENT -> {
                val rid = p.roteiroId ?: return@op
                when (val r = api.segment(rid, p.id)) {
                    // "uncertain" = Grok still planning on the PC: keep the record, only a later GET resolves it.
                    is ApiResult.Ok -> if (r.value.state == "uncertain") say("Planning still in progress on PC.") else {
                        resolve(p.id); acceptSegment(rid, p.blockId, r.value)
                    }
                    is ApiResult.Http -> if (r.code == 404) { resolve(p.id); clearSegmentId(rid, p.blockId); say("The PC did not register this plan.") } else say(r.message())
                    else -> say(r.message())
                }
            }
            OpKind.ASSEMBLY -> when (val r = api.assembly(p.id)) {
                is ApiResult.Ok -> if (r.value.state == "running") say("Assembly still in progress on PC.") else {
                    resolve(p.id); say("Assembly ${r.value.id.take(8)}: ${r.value.state}"); loadAssemblies()
                }
                is ApiResult.Http -> if (r.code == 404) { resolve(p.id); say("The PC did not register this assembly.") } else say(r.message())
                else -> say(r.message())
            }
            OpKind.ATTEMPT -> {
                val rid = p.roteiroId ?: return@op
                val bid = p.blockId ?: return@op
                when (val r = api.getAttempt(rid, bid, p.id)) {
                    is ApiResult.Ok -> when (r.value.admission) {
                        "admitted" -> { resolve(p.id); say("Submission confirmed: ${RunStates.label(r.value.state)}.") }
                        "rejected" -> { resolve(p.id); say("The PC rejected this submission${r.value.error?.let { ": $it" } ?: ""}. You can prepare another.") }
                        else -> say("Still uncertain on PC. Check again later.")
                    }
                    is ApiResult.Http -> if (r.code == 404) { resolve(p.id); say("The PC did not register this submission. You can prepare again.") } else say(r.message())
                    else -> say(r.message())
                }
            }
            OpKind.EDIT -> {
                val rid = p.roteiroId ?: return@op
                when (val r = api.edit(rid, p.id)) {
                    is ApiResult.Ok -> {
                        edits[rid + ":" + r.value.blockId] = Remote(r.value)
                        if (r.value.state == "improving") say("Grok is still proposing this edit on PC.")
                        else { resolve(p.id); say("Edit: ${r.value.state}") }
                    }
                    is ApiResult.Http -> if (r.code == 404) {
                        resolve(p.id); p.blockId?.let { b -> if (drafts.editId(rid, b) == p.id) drafts.clearEditId(rid, b); edits.remove("$rid:$b") }
                        say("The PC did not register this edit.")
                    } else say(r.message())
                    else -> say(r.message())
                }
            }
            OpKind.DECISION -> when (val r = api.run(p.id)) {
                is ApiResult.Ok -> {
                    resolve(p.id)
                    say(if (r.value.state == RunStates.READY) "Decision did not reach PC; video is still up for review."
                        else "State on PC: ${RunStates.label(r.value.state)}.")
                }
                else -> say(r.message())
            }
        }
        p.roteiroId?.let { reloadRoteiro(it) }
    }

    // ---------------- block actions ----------------

    fun saveBlock(roteiroId: String, block: Block) = op("save:${block.id}") {
        val doc = doc(roteiroId) ?: return@op
        if (!doc.adopted) {
            val c = candidate(roteiroId) ?: return@op
            saveCandidate(roteiroId, c.copy(blocks = c.blocks.map { if (it.id == block.id) block else it }))
            say("Draft saved on this device.")
            return@op
        }
        val r = api.putRoteiro(doc, doc.blocks.map { if (it.id == block.id) block else it })
        when (r) {
            is ApiResult.Ok -> { store(r.value); say("Block saved on PC.") }
            else -> { say(if (r is ApiResult.Http && r.code == 409) "The script changed on PC and was reloaded. Your edit was kept." else r.message()); reloadRoteiro(roteiroId) }
        }
    }

    fun deletePlanned(roteiroId: String, blockId: String) = op("remove:$blockId") {
        val doc = doc(roteiroId) ?: return@op
        if (!doc.adopted) {
            val c = candidate(roteiroId) ?: return@op
            saveCandidate(roteiroId, c.copy(blocks = c.blocks.filter { it.id != blockId }))
            leave(Screen.Block(roteiroId, blockId))
            return@op
        }
        if (doc.blocks.size <= 1) { say("An adopted script needs at least one block."); return@op }
        when (val r = api.putRoteiro(doc, doc.blocks.filter { it.id != blockId })) {
            is ApiResult.Ok -> { store(r.value); leave(Screen.Block(roteiroId, blockId)); say("Block deleted.") }
            else -> { say(r.message()); reloadRoteiro(roteiroId) }
        }
    }

    /** "Tirar da sequência" for a block with attempts: media and history stay on the PC. */
    fun removeFromSequence(roteiroId: String, blockId: String) = op("remove:$blockId") {
        val doc = reloadRoteiro(roteiroId) ?: return@op
        when (val r = api.removeBlock(roteiroId, blockId, doc.revision)) {
            is ApiResult.Ok -> { store(r.value); leave(Screen.Block(roteiroId, blockId)); say("Block removed from sequence. The video remains on PC.") }
            else -> { say(r.message()); reloadRoteiro(roteiroId) }
        }
    }

    fun generateBlock(roteiroId: String, blockId: String) = op("attempt:$roteiroId") {
        val doc = reloadRoteiro(roteiroId) ?: return@op
        val index = doc.index(blockId)
        val block = doc.blocks.getOrNull(index) ?: return@op
        val parent = RoteiroLogic.parentForFirstAttempt(doc, index).getOrElse { say(it.message ?: "No accepted parent."); return@op }
        attempt(doc, blockId, block.prompt, block.seed, block.durationSeconds, parent)
    }

    fun retryBlock(roteiroId: String, blockId: String, prompt: String, durationText: String, seedText: String) = op("attempt:$roteiroId") {
        val duration = Durations.parse(durationText)?.toDouble() ?: run { say("Invalid duration."); return@op }
        val seed = Durations.parseSeed(seedText) ?: run { say("Invalid seed."); return@op }
        if (prompt.isBlank()) { say("Prompt cannot be empty."); return@op }
        val doc = reloadRoteiro(roteiroId) ?: return@op
        val plan = RoteiroLogic.retryPlan(doc, blockId) ?: run { say("This block cannot be retried right now."); return@op }
        attempt(doc, blockId, prompt, seed, duration, plan.parentId, plan.targetRunId)
    }

    private suspend fun attempt(doc: Roteiro, blockId: String, prompt: String, seed: Long, duration: Double, parent: String?,
                                target: String? = null) {
        if (pendingStore.find(OpKind.ATTEMPT, doc.id) != null) { say("There is an unconfirmed submission in this script; check it first."); return }
        val p = begin(PendingOp(OpKind.ATTEMPT, newUuid(), doc.id, blockId))
        val r = api.postAttempt(doc.id, blockId, p.id, doc.revision, prompt, seed, duration, parent, target)
        if (r is ApiResult.Ok && r.value.admission == "admitted" && r.value.runId == p.id) {
            resolve(p.id)
            say("Submitted to PC: ${RunStates.label(r.value.state)}.")
        } else {
            settle(p, if (r is ApiResult.Ok) ApiResult.Network("uncertain admission") else r)
            say("${r.message().ifBlank { "Uncertain admission" }} · Check this submission before any other.")
        }
        reloadRoteiro(doc.id)
    }

    fun decide(roteiroId: String, blockId: String?, runId: String, accept: Boolean, after: (() -> Unit)? = null) = op("decide:$runId") {
        if (pendingStore.get(runId) != null) { say("Previous decision has no response; reload the video."); return@op }
        val p = begin(PendingOp(OpKind.DECISION, runId, roteiroId, blockId, if (accept) "accept" else "reject"))
        val r = api.decide(runId, accept)
        settle(p, r)
        when {
            r is ApiResult.Ok -> { say(if (accept) "Accepted." else "Rejected. Video and history remain on PC."); after?.invoke() }
            r.uncertain -> say("Uncertain decision. Reload the video; do not repeat the decision.")
            else -> say(r.message())
        }
        reloadRoteiro(roteiroId)
    }

    fun stopRun(roteiroId: String, runId: String) = op("stop:$runId") {
        val b = batchOn(roteiroId)
        // A run owned by the active batch is stopped through the batch, like the web client.
        val r = if (b != null && b.currentRunId == runId) api.stopBatch(roteiroId, b.id).map { } else api.stopRun(runId).map { }
        say(if (r is ApiResult.Ok) "Stop requested." else r.message())
        loadBatch()
        reloadRoteiro(roteiroId)
    }

    fun selectVersion(roteiroId: String, blockId: String, runId: String) = op("version:$blockId") {
        val doc = reloadRoteiro(roteiroId) ?: return@op
        when (val r = api.selectVersion(roteiroId, blockId, runId, doc.revision)) {
            is ApiResult.Ok -> { store(r.value); say("Version ${runId.take(8)} in use.") }
            else -> { say(r.message()); reloadRoteiro(roteiroId) }
        }
    }

    // ---------------- T4/T7 insert N blocks ----------------

    private var insertTick by mutableIntStateOf(0)
    private val insertCache = HashMap<String, InsertDraft>()

    fun insertDraft(roteiroId: String, after: String?): InsertDraft {
        insertTick
        return insertCache.getOrPut("$roteiroId:$after") {
            drafts.insert(roteiroId, after) ?: run {
                val seed = doc(roteiroId)?.blocks?.firstOrNull { it.id == after }?.seed ?: Durations.DEFAULT_SEED
                InsertDraft(seedText = seed.toString())
            }
        }
    }

    fun updateInsert(roteiroId: String, after: String?, d: InsertDraft) {
        insertCache["$roteiroId:$after"] = d
        drafts.saveInsert(roteiroId, after, d)
        insertTick++
    }

    fun discardInsert(roteiroId: String, after: String?) {
        insertCache.remove("$roteiroId:$after")
        drafts.clearInsert(roteiroId, after)
        insertTick++
    }

    private fun clearSegmentId(roteiroId: String, after: String?) {
        val d = insertDraft(roteiroId, after)
        updateInsert(roteiroId, after, d.copy(segmentId = null))
    }

    private fun acceptSegment(roteiroId: String, after: String?, record: SegmentRecord) {
        segments[record.id] = record
        when (record.state) {
            "proposed" -> {
                updateInsert(roteiroId, after, insertDraft(roteiroId, after).copy(segmentId = record.id, blocks = record.blocks,
                    scenes = record.scenes, vision = record.vision))
                say("${record.blocks.size} blocks planned. Review and insert.")
            }
            "invalid" -> {
                invalidAnswer = (listOfNotNull(record.error, record.detail) + record.rawTexts).joinToString("\n\n")
                say("Grok returned an invalid plan; nothing was inserted.")
            }
            else -> say("Plan still uncertain on PC.")
        }
    }

    /** Restores a planned segment after process death (read only). */
    fun ensureSegment(roteiroId: String, after: String?) {
        val d = insertDraft(roteiroId, after)
        val id = d.segmentId ?: return
        if (segments.containsKey(id) || pendingStore.get(id) != null || isBusy("segment:$roteiroId")) return
        op("segment-read:$id") {
            val r = api.segment(roteiroId, id)
            if (r is ApiResult.Ok) segments[id] = r.value
        }
    }

    fun planSegment(roteiroId: String, after: String?) = op("segment:$roteiroId") {
        val d = insertDraft(roteiroId, after)
        val duration = Durations.parse(d.durationText)?.toDouble() ?: run { say("Invalid duration."); return@op }
        val seed = Durations.parseSeed(d.seedText) ?: run { say("Invalid seed."); return@op }
        if (d.idea.isBlank()) { say("Write what happens in these blocks."); return@op }
        if (pendingStore.find(OpKind.SEGMENT, roteiroId) != null) { say("There is an unconfirmed plan; check it first."); return@op }
        val doc = reloadRoteiro(roteiroId) ?: return@op
        val count = d.count.coerceAtMost(MAX_BLOCKS - doc.blocks.size)
        if (count < 1) { say("The script already has $MAX_BLOCKS blocks."); return@op }
        val p = begin(PendingOp(OpKind.SEGMENT, newUuid(), roteiroId, after))
        updateInsert(roteiroId, after, insertDraft(roteiroId, after).copy(segmentId = p.id, blocks = emptyList(), scenes = emptyList(), vision = null))
        val r = api.planSegment(roteiroId, p.id, doc.revision, after, d.idea.trim(), count, duration, seed)
        settle(p, r)
        when {
            r is ApiResult.Ok -> acceptSegment(roteiroId, after, r.value)
            r is ApiResult.Http && r.body?.get("state") != null && r.code < 500 ->
                acceptSegment(roteiroId, after, SegmentRecord.parse(r.body))
            r.uncertain -> say("No response from Grok/PC. Check the same plan.")
            else -> { say(r.message()); clearSegmentId(roteiroId, after) }
        }
    }

    fun manualInsert(roteiroId: String, after: String?) {
        val d = insertDraft(roteiroId, after)
        val duration = Durations.parse(d.durationText)?.toDouble() ?: run { say("Invalid duration."); return }
        val seed = Durations.parseSeed(d.seedText) ?: run { say("Invalid seed."); return }
        if (d.idea.isBlank()) { say("Write what happens in these blocks."); return }
        val count = d.count.coerceAtMost(MAX_BLOCKS - (doc(roteiroId)?.blocks?.size ?: 0))
        if (count < 1) { say("The script already has $MAX_BLOCKS blocks."); return }
        updateInsert(roteiroId, after, d.copy(segmentId = null, scenes = emptyList(), vision = null,
            blocks = RoteiroLogic.manualBlocks(count, d.idea, duration, seed)))
    }

    fun applyInsert(roteiroId: String, after: String?) = op("insert:$roteiroId") {
        val d = insertDraft(roteiroId, after)
        if (d.blocks.isEmpty()) return@op
        val doc = reloadRoteiro(roteiroId) ?: return@op
        val blocks = RoteiroLogic.splice(doc.blocks, after, d.blocks)
            ?: run { say("The reference block is no longer in the script."); return@op }
        if (blocks.size > MAX_BLOCKS) { say("The script would exceed $MAX_BLOCKS blocks."); return@op }
        val r = api.putRoteiro(doc, blocks)
        val done = r is ApiResult.Ok || (r.uncertain && reloadRoteiro(roteiroId)?.blocks?.map { it.id }?.containsAll(d.blocks.map { it.id }) == true)
        if (r is ApiResult.Ok) store(r.value)
        if (done) {
            discardInsert(roteiroId, after)
            leave(Screen.Insert(roteiroId, after))
            say("${d.blocks.size} blocks inserted. Use “Generate pending”.")
        } else say(r.message())
    }

    // ---------------- redo block (anchored edit, replace) ----------------

    private fun editKey(roteiroId: String, blockId: String) = "$roteiroId:$blockId"

    fun ensureRedo(roteiroId: String, blockId: String) {
        if (edits.containsKey(editKey(roteiroId, blockId))) return
        val saved = drafts.editId(roteiroId, blockId)
        if (saved != null) { loadEdit(roteiroId, blockId, saved); return }
        op("edit-list:$roteiroId") {
            val r = api.edits(roteiroId)
            val open = r.valueOrNull()?.lastOrNull { it.blockId == blockId && it.mode == "replace" && it.open }
            if (open != null) {
                drafts.saveEditId(roteiroId, blockId, open.id)
                edits[editKey(roteiroId, blockId)] = Remote(open)
            } else if (r !is ApiResult.Ok) say(r.message())
        }
    }

    fun loadEdit(roteiroId: String, blockId: String, editId: String) = viewModelScope.launch {
        val key = editKey(roteiroId, blockId)
        edits[key] = (edits[key] ?: Remote()).copy(loading = true)
        edits[key] = when (val r = api.edit(roteiroId, editId)) {
            is ApiResult.Ok -> Remote(r.value)
            else -> Remote(edits[key]?.value, false, r.message())
        }
    }

    fun proposeRedo(roteiroId: String, blockId: String, idea: String, durationText: String, seedText: String) = op("redo:$blockId") {
        val duration = Durations.parse(durationText)?.toDouble() ?: run { say("Invalid duration."); return@op }
        val seed = Durations.parseSeed(seedText) ?: run { say("Invalid seed."); return@op }
        if (idea.isBlank()) { say("Describe the new version."); return@op }
        if (pendingStore.find(OpKind.EDIT, roteiroId) != null) { say("There is an unconfirmed edit; check it first."); return@op }
        val doc = reloadRoteiro(roteiroId) ?: return@op
        val p = begin(PendingOp(OpKind.EDIT, newUuid(), roteiroId, blockId))
        drafts.saveEditId(roteiroId, blockId, p.id)
        val r = api.proposeEdit(roteiroId, p.id, doc.revision, blockId, idea.trim(), seed, duration)
        settle(p, r)
        when {
            r is ApiResult.Ok -> edits[editKey(roteiroId, blockId)] = Remote(r.value)
            r.uncertain -> say("No response from Grok/PC. Check the same edit.")
            else -> { drafts.clearEditId(roteiroId, blockId); say(r.message()) }
        }
    }

    fun generateRedo(roteiroId: String, blockId: String, prompt: String) = op("redo:$blockId") {
        val record = edits[editKey(roteiroId, blockId)]?.value ?: return@op
        if (prompt.isBlank()) { say("Prompt cannot be empty."); return@op }
        if (pendingStore.get(record.id) != null) { say("This edit has no response; check it first."); return@op }
        val p = begin(PendingOp(OpKind.EDIT, record.id, roteiroId, blockId))
        val r = api.generateEdit(roteiroId, record.id, prompt)
        settle(p, r)
        when {
            r is ApiResult.Ok -> { edits[editKey(roteiroId, blockId)] = Remote(r.value); say("Generation submitted to PC.") }
            r.uncertain -> say("Uncertain response. Check the same edit; do not generate again.")
            else -> { say(r.message()); loadEdit(roteiroId, blockId, record.id) } // a refusal may have marked it failed
        }
    }

    fun applyRedo(roteiroId: String, blockId: String) = op("redo:$blockId") {
        val record = edits[editKey(roteiroId, blockId)]?.value ?: return@op
        when (val r = api.applyEdit(roteiroId, record.id, record.sourceRevision)) {
            is ApiResult.Ok -> {
                store(r.value)
                drafts.clearEditId(roteiroId, blockId)
                edits.remove(editKey(roteiroId, blockId))
                leave(Screen.Redo(roteiroId, blockId))
                say("New version in use in script.")
            }
            else -> { say(r.message()); loadEdit(roteiroId, blockId, record.id) }
        }
    }

    fun discardRedo(roteiroId: String, blockId: String) = op("redo:$blockId") {
        val record = edits[editKey(roteiroId, blockId)]?.value ?: return@op
        when (val r = api.discardEdit(roteiroId, record.id)) {
            is ApiResult.Ok -> { drafts.clearEditId(roteiroId, blockId); edits.remove(editKey(roteiroId, blockId)); say("Edit discarded.") }
            else -> say(r.message())
        }
    }

    fun retryRedo(roteiroId: String, blockId: String) = op("redo:$blockId") {
        val record = edits[editKey(roteiroId, blockId)]?.value ?: return@op
        if (pendingStore.find(OpKind.EDIT, roteiroId) != null) { say("There is an unconfirmed edit; check it first."); return@op }
        val doc = reloadRoteiro(roteiroId) ?: return@op
        val p = begin(PendingOp(OpKind.EDIT, newUuid(), roteiroId, blockId))
        val r = api.retryEdit(roteiroId, record.id, p.id, doc.revision)
        settle(p, r)
        when {
            r is ApiResult.Ok -> { drafts.saveEditId(roteiroId, blockId, p.id); edits[editKey(roteiroId, blockId)] = Remote(r.value) }
            r.uncertain -> { drafts.saveEditId(roteiroId, blockId, p.id); say("Uncertain response. Check the same edit.") }
            else -> say(r.message())
        }
    }

    // ---------------- T8 assembly ----------------

    fun loadAssemblies() = viewModelScope.launch {
        assemblies = assemblies.copy(loading = true)
        assemblies = when (val r = api.assemblies()) {
            is ApiResult.Ok -> Remote(r.value)
            else -> Remote(assemblies.value, false, r.message())
        }
    }

    fun assemble(roteiroId: String) = op("assemble:$roteiroId") {
        if (pendingStore.find(OpKind.ASSEMBLY, roteiroId) != null) { say("There is an unconfirmed assembly; check it first."); return@op }
        val doc = reloadRoteiro(roteiroId) ?: return@op
        val p = begin(PendingOp(OpKind.ASSEMBLY, newUuid(), roteiroId))
        val r = api.assemble(roteiroId, p.id, doc.revision)
        settle(p, r)
        when {
            r is ApiResult.Ok -> say("Assembly ready: ${r.value.frames ?: "?"} frames.")
            r.uncertain -> say("Uncertain response. Reload the same assembly.")
            else -> say(r.message())
        }
        loadAssemblies()
    }

    fun downloadAssembly(a: Assembly, roteiroId: String) {
        VideoDownloadWorker.enqueueAssembly(ctx, settings.baseUrl, a.id, roteiroId)
        say("Downloading to Movies/H3 Studio…")
    }

    fun localVideo(runId: String): File? = VideoDownloadWorker.localRunVideo(ctx, runId)

    // ---------------- T9 settings ----------------

    fun loadEditors() = viewModelScope.launch {
        for (path in listOf(ApiClient.ROTEIRO_EDITOR, ApiClient.GROK_EDITOR, ApiClient.EDIT_EDITOR)) {
            launch {
                editors[path] = (editors[path] ?: Remote()).copy(loading = true)
                editors[path] = when (val r = api.editor(path)) {
                    is ApiResult.Ok -> Remote(r.value)
                    else -> Remote(editors[path]?.value, false, r.message())
                }
            }
        }
    }

    fun saveEditor(path: String, systemPrompt: String) = op("editor:$path") {
        if (systemPrompt.isBlank()) { say("System prompt cannot be empty."); return@op }
        // Only /grok/editor carries the model, and it must equal the PC's pin (read-only here).
        val model = if (path == ApiClient.GROK_EDITOR) editors[path]?.value?.model ?: run { say("Read configuration first."); return@op } else null
        when (val r = api.saveEditor(path, systemPrompt, model)) {
            is ApiResult.Ok -> { editors[path] = Remote(r.value); say("Saved to PC.") }
            else -> say(r.message())
        }
    }

    fun testServer(url: String) = op("server") {
        val candidate = url.trim().trimEnd('/')
        if (!candidate.startsWith("http://") && !candidate.startsWith("https://")) { say("Use http://IP:port"); return@op }
        val probe = ApiClient { candidate }
        when (val r = probe.config()) {
            is ApiResult.Ok -> {
                val changed = candidate != settings.baseUrl
                settings.baseUrl = candidate
                say("PC responded at $candidate.")
                if (changed) {
                    onBackground(); onForeground()
                    settings.fcmToken?.let { H3App.registerToken(ctx, it) }
                }
            }
            else -> say(r.message())
        }
    }

    fun registerNotifications() {
        val token = settings.fcmToken ?: run { say("No notification token on this device yet."); return }
        H3App.registerToken(ctx, token) { text -> viewModelScope.launch { say(text) } }
    }

    fun storageInfo(): Triple<Int, Long, Long> {
        val (count, bytes) = VideoDownloadWorker.storedBytes(ctx)
        return Triple(count, bytes, com.al4xdev.h3.data.MediaCache.cacheBytes(ctx))
    }

    fun clearStorage() {
        VideoDownloadWorker.clearStored(ctx)
        com.al4xdev.h3.data.MediaCache.clear(ctx)
        say("Downloaded videos and thumbnails cleared from this device.")
    }

    override fun onCleared() {
        onBackground()
        super.onCleared()
    }

    companion object {
        private const val NAV_KEY = "nav"
        private const val FORWARD_KEY = "nav_forward"
        private const val MAX_UPLOAD = 20L * 1024 * 1024
    }
}
