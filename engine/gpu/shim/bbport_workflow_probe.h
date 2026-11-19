// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum {
    WORKFLOW_PATH_MAX = 1024,
    WORKFLOW_REQUEST_LIMIT = 64,
    WORKFLOW_REQUEST_BYTES = 4096,
    WORKFLOW_LOG_RECORD_BYTES = 8192,
    WORKFLOW_FILE_NAMES = 256,
    WORKFLOW_FILE_SNAPSHOTS = 8,
    WORKFLOW_FILE_BYTES = 4 * 1024 * 1024,
    WORKFLOW_DRAW_BYTES = 1024 * 1024,
    WORKFLOW_PAYLOAD_BYTES = 16 * 1024 * 1024,
    WORKFLOW_TRANSFER_LIMIT = 3,
    WORKFLOW_NATIVE_WIDTH = 1920,
    WORKFLOW_NATIVE_HEIGHT = 1080,
    WORKFLOW_NATIVE_FRAMES = 96,
};

typedef struct WorkflowProbeConfig {
    const char* directory;
    const char* session;
    const char* map;
} WorkflowProbeConfig;

#ifdef __cplusplus
extern "C" {
#endif
int workflow_log_record(const char* line, size_t bytes);
#ifdef __cplusplus
}
#endif

static inline int workflow_session_valid(const char* session) {
    if (!session) return 0;
    const size_t n = strlen(session);
    return n > 0 && n <= 32 && strspn(session, "abcdefghijklmnopqrstuvwxyz0123456789-") == n;
}

static inline int workflow_map_valid(const char* map) {
    if (!map || strlen(map) != 12 || map[0] != 'm') return 0;
    for (size_t i = 1; i < 12; ++i) {
        if (i == 3 || i == 6 || i == 9) {
            if (map[i] != '_') return 0;
        } else if (map[i] < '0' || map[i] > '9') {
            return 0;
        }
    }
    return 1;
}

// The host names the directory once at startup. Requests carry only IDs.
static inline int workflow_capture_root_read(WorkflowProbeConfig* cfg) {
    cfg->directory = getenv("BB_WORKFLOW_PROBE_DIR");
    cfg->session = getenv("BB_WORKFLOW_SESSION");
    cfg->map = getenv("BB_WORKFLOW_MAP");
    const char* dir = cfg->directory;
    if (!dir || !*dir || strlen(dir) > WORKFLOW_PATH_MAX - 128 ||
        !workflow_session_valid(cfg->session)) return 0;
#ifdef _WIN32
    return ((dir[0] >= 'a' && dir[0] <= 'z') || (dir[0] >= 'A' && dir[0] <= 'Z')) &&
           dir[1] == ':' && (dir[2] == '/' || dir[2] == '\\');
#else
    return dir[0] == '/';
#endif
}

static inline int workflow_config_read(WorkflowProbeConfig* cfg) {
    return workflow_capture_root_read(cfg) && workflow_map_valid(cfg->map);
}

static inline int workflow_path(const WorkflowProbeConfig* cfg, const char* name, char* path) {
    if (!name || !*name || strspn(name, "abcdefghijklmnopqrstuvwxyz0123456789-.") != strlen(name) ||
        !strcmp(name, ".") || !strcmp(name, "..")) return 0;
    const int n = snprintf(path, WORKFLOW_PATH_MAX, "%s/%s", cfg->directory, name);
    return n > 0 && n < WORKFLOW_PATH_MAX;
}

