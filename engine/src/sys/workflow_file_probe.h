// SPDX-License-Identifier: GPL-3.0-or-later
// Included by sys/file.c after its native file-ID and path folding helpers.
#pragma once

typedef struct WorkflowFile {
    uint64_t token;
    FILE_ID_INFO identity;
    HANDLE hold;
    const char* route;
    size_t size, covered;
    unsigned char *snapshot, *coverage;
    char logical[256];
    int coherent, complete;
} WorkflowFile;

static WorkflowProbeConfig workflow_files;
static int workflow_files_enabled;
static uint64_t workflow_open_count;
static unsigned workflow_snapshot_count;
static char (*workflow_watch)[256];
static size_t workflow_watch_count;

static int workflow_logical_valid(const char* name) {
    size_t n = strlen(name);
    return n > 0 && n < sizeof(((WorkflowFile*)0)->logical) && name[0] != '/' &&
           !strstr(name, "..") && !strstr(name, "//") &&
           strspn(name, "abcdefghijklmnopqrstuvwxyz0123456789-._/") == n;
}

static void workflow_files_configure(void) {
    if (workflow_files_enabled || !workflow_config_read(&workflow_files)) return;
    workflow_files_enabled = 1;
    char path[WORKFLOW_PATH_MAX];
    if (!workflow_path(&workflow_files, "watch.txt", path)) return;
    FILE* file = fopen(path, "rb");
    if (!file) return;
    workflow_watch = calloc(WORKFLOW_FILE_NAMES, sizeof(*workflow_watch));
    char line[258];
    int valid = workflow_watch != NULL;
    while (workflow_watch && workflow_watch_count < WORKFLOW_FILE_NAMES && fgets(line, sizeof(line), file)) {
        const size_t n = strlen(line);
        if (n <= 1 || line[n - 1] != '\n') { valid = 0; break; }
        line[n - 1] = 0;
        if (!workflow_logical_valid(line)) { valid = 0; break; }
        memcpy(workflow_watch[workflow_watch_count++], line, n);
    }
    const int complete = valid && !ferror(file) && fgetc(file) == EOF;
    if (!complete || !feof(file)) {
        workflow_watch_count = 0;
        char row[256];
        const int size = snprintf(row, sizeof(row), "\nWorkflow probe: {\"schema\":\"bb-workflow-probe-v1\","
                                  "\"session\":\"%s\",\"pid\":%lu,\"request\":0,\"op\":\"files\","
                                  "\"event\":\"watch\",\"status\":\"refused\","
                                  "\"reason\":\"watch_invalid_or_over_budget\"}\n",
                                  workflow_files.session, (unsigned long)GetCurrentProcessId());
        if (size > 0 && (size_t)size < sizeof(row)) workflow_log_record(row, (size_t)size);
    }
    fclose(file);
}

static void workflow_file_event(const WorkflowFile* p, const char* event, const char* status,
                                const char* reason, int64_t at, int64_t bytes, const char* blob) {
    char id[16 * 2 + 1] = "";
    for (size_t i = 0; i < sizeof(p->identity.FileId.Identifier); ++i)
        snprintf(id + i * 2, sizeof(id) - i * 2, "%02x", p->identity.FileId.Identifier[i]);
    char blob_json[88] = "null";
    if (blob) snprintf(blob_json, sizeof(blob_json), "\"%s\"", blob);
    char row[1536];
    const int size = snprintf(row, sizeof(row),
                              "\nWorkflow probe: {\"schema\":\"bb-workflow-probe-v1\",\"session\":\"%s\","
                              "\"pid\":%lu,\"request\":0,\"op\":\"files\",\"event\":\"%s\",\"status\":\"%s\","
                              "\"reason\":\"%s\",\"open_token\":%llu,\"logical_path\":\"%s\","
                              "\"file_identity\":\"%016llx-%s\",\"loader_route\":\"%s\","
                              "\"layer\":null,\"layer_reason\":\"named_layers_require_host_content_join\","
                              "\"byte_count\":%llu,\"delivered_offset\":%lld,\"delivered_bytes\":%lld,\"covered\":%llu,"
                              "\"guest_delivery_complete\":%s,\"blob\":%s}\n",
                              workflow_files.session, (unsigned long)GetCurrentProcessId(), event, status, reason,
                              (unsigned long long)p->token, p->logical,
                              (unsigned long long)p->identity.VolumeSerialNumber, id, p->route ? p->route : "unknown",
                              (unsigned long long)p->size, (long long)at, (long long)bytes,
                              (unsigned long long)p->covered, p->complete ? "true" : "false", blob_json);
    if (size > 0 && (size_t)size < sizeof(row)) workflow_log_record(row, (size_t)size);
}

static void workflow_file_free(WorkflowFile* p) {
    if (!p) return;
    workflow_file_event(p, "file_close", p->complete ? "ok" : "unsupported",
                        p->complete ? "full_guest_delivery" : "partial_or_unwitnessed_delivery", -1, 0, NULL);
    if (p->hold != INVALID_HANDLE_VALUE) CloseHandle(p->hold);
    free(p->snapshot);
    free(p->coverage);
    free(p);
}

static WorkflowFile* workflow_file_open(const char* guest, int host, const char* route) {
    const char* raw = !strncmp(guest, "/app0/", 6) ? guest + 6 :
                      !strncmp(guest, "/hostapp/", 9) ? guest + 9 : *guest != '/' ? guest : NULL;
    WorkflowFile seed = {.hold = INVALID_HANDLE_VALUE, .route = route};
    if (!raw || strlen(raw) >= sizeof(seed.logical)) return NULL;
    memcpy(seed.logical, raw, strlen(raw) + 1);
    fold_path(seed.logical);
    if (!workflow_logical_valid(seed.logical)) return NULL;

    int watched = 0;
    for (size_t i = 0; i < workflow_watch_count; ++i) {
        if (!strcmp(seed.logical, workflow_watch[i])) {
            watched = 1;
            break;
        }
    }
    char prefix[64];
    const int n = snprintf(prefix, sizeof(prefix), "dvdroot_ps4/map/%s/", workflow_files.map);
    const int in_map = n > 0 && n < (int)sizeof(prefix) && !strncmp(seed.logical, prefix, (size_t)n);
    if (!watched && !in_map) return NULL;
    seed.token = __atomic_add_fetch(&workflow_open_count, 1, __ATOMIC_RELAXED);
    if (seed.token > WORKFLOW_FILE_NAMES) {
        if (seed.token == WORKFLOW_FILE_NAMES + 1)
            workflow_file_event(&seed, "file_open", "unsupported", "matching_open_limit", -1, 0, NULL);
        return NULL;
    }

    HostStat st;
    const HANDLE effective = (HANDLE)_get_osfhandle(host);
    if (!round2_file_id(effective, &seed.identity) ||
        host_fstat(host, &st) || !S_ISREG(st.st_mode) || st.st_size <= 0) {
        workflow_file_event(&seed, "file_open", "unsupported", "native_file_identity_unavailable", -1, 0, NULL);
        return NULL;
    }
    seed.size = (size_t)st.st_size;
    if (!watched || seed.size > WORKFLOW_FILE_BYTES) {
        workflow_file_event(&seed, "file_open", "ok",
                            !watched ? "observed_map_candidate" : "observed_oversize_candidate", -1, 0, NULL);
        return NULL;
    }

    ULARGE_INTEGER available;
    if (!GetDiskFreeSpaceExA(workflow_files.directory, &available, NULL, NULL) || available.QuadPart < seed.size) {
        workflow_file_event(&seed, "file_open", "unsupported", "file_output_headroom", -1, 0, NULL);
        return NULL;
    }
    unsigned admitted = __atomic_fetch_add(&workflow_snapshot_count, 1, __ATOMIC_RELAXED);
    if (admitted >= WORKFLOW_FILE_SNAPSHOTS || !workflow_payload_reserve(seed.size)) {
        workflow_file_event(&seed, "file_open", "unsupported", "file_snapshot_budget", -1, 0, NULL);
        return NULL;
    }
    // ReOpenFile binds the same file object with write/delete sharing denied. The game fd supplies the bytes.
    seed.hold = ReOpenFile(effective, GENERIC_READ, FILE_SHARE_READ, 0);
    FILE_ID_INFO held;
    if (!round2_file_id(seed.hold, &held) || !round2_same_id(&seed.identity, &held)) {
        if (seed.hold != INVALID_HANDLE_VALUE) CloseHandle(seed.hold);
        workflow_file_event(&seed, "file_open", "unsupported", "immutable_descriptor_unavailable", -1, 0, NULL);
        return NULL;
    }
    WorkflowFile* p = malloc(sizeof(*p));
    if (!p) {
        CloseHandle(seed.hold);
        workflow_file_event(&seed, "file_open", "unsupported", "file_snapshot_allocation", -1, 0, NULL);
        return NULL;
    }
    *p = seed;
    p->snapshot = malloc(p->size);
    p->coverage = calloc((p->size + 7) / 8, 1);
    p->coherent = p->snapshot && p->coverage &&
                  pread(host, p->snapshot, p->size, 0) == (int64_t)p->size;
    char name[64], path[WORKFLOW_PATH_MAX];
    snprintf(name, sizeof(name), "workflow-file-%llu.bin", (unsigned long long)p->token);
    FILE* out = p->coherent && workflow_path(&workflow_files, name, path) ? fopen(path, "wbx") : NULL;
    int written = 0;
    if (out) {
        written = fwrite(p->snapshot, 1, p->size, out) == p->size;
        if (fclose(out)) written = 0;
        if (!written) unlink(path);
    }
    workflow_file_event(p, "file_open", written ? "ok" : "unsupported",
                        written ? "immutable_actual_descriptor_snapshot" : "file_snapshot_incomplete", -1, 0,
                        written ? name : NULL);
    if (!written) {
        workflow_file_free(p);
        return NULL;
    }
    return p;
}

static void workflow_file_delivered(WorkflowFile* p, int64_t offset, const void* data, int64_t bytes) {
    if (!p->coherent || bytes <= 0) return;
    if (offset < 0 || (uint64_t)offset > p->size || (uint64_t)bytes > p->size - (size_t)offset ||
        memcmp(p->snapshot + offset, data, (size_t)bytes)) {
        p->coherent = p->complete = 0;
        workflow_file_event(p, "file_delivery", "refused", "guest_bytes_or_offset_mismatch", offset, bytes, NULL);
        return;
    }
    if (p->complete) return;
    for (size_t i = (size_t)offset, end = i + (size_t)bytes; i < end; ++i) {
        const unsigned char bit = (unsigned char)(1u << (i % 8));
        if (p->coverage[i / 8] & bit) continue;
        p->coverage[i / 8] |= bit;
        ++p->covered;
    }
    p->complete = p->covered == p->size;
    if (p->complete)
        workflow_file_event(p, "file_delivery", "ok", "full_guest_delivery", offset, bytes, NULL);
}

