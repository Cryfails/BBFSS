// SPDX-License-Identifier: GPL-3.0-or-later
#include "sys.h"
#include "pad.h"
#include "gpu/bbgpu.h"
#include "gpu/shim/input/input.h"
#include "host_sync.h"
#include <inttypes.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifndef _WIN32
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#endif

enum {
    PAD_ERROR_ARGUMENT = (int32_t)0x80920001,
    PAD_ERROR_HANDLE = (int32_t)0x80920003,
    PAD_ERROR_OPENED = (int32_t)0x80920004,
    PAD_ERROR_NOT_INITIALIZED = (int32_t)0x80920005,
};

#define THE_HANDLE 1
#define THE_USER 1
#define PAD_TYPE_STANDARD 0
#define PAD_TYPE_SPECIAL 2

typedef struct {
    float pixel_density;
    uint16_t resolution_x, resolution_y;
    uint8_t dead_zone_left, dead_zone_right, connection_type, connected_count;
    uint8_t connected, padding[3];
    int32_t device_class;
    uint8_t reserved[8];
} PadControllerInfo;
_Static_assert(sizeof(PadControllerInfo) == 28, "PadControllerInfo is 28 bytes");

static HostMutex lock = HOST_MUTEX_INIT;
static int initialized, opened, holding_after_overlay;
static size_t reads;

enum { PAD_RECEIPT_MAX = 600 };
typedef struct {
    uint64_t serial, monotonic_ns;
    unsigned owner_generation;
    PadScriptReceipt script;
    PadData pre, final;
    int owner_ok;
} GuestPadRead;

typedef struct {
    BbSewerPadStatus status;
    uint64_t observed_command;
    int inherited_rx;
    BbPcRestWitness pc;
    uint8_t pc_rest;
} GuestLatchRead;

static char receipt_nonce[17], *receipt_path;
static atomic_int receipt_enabled;
static atomic_uint owner_generation;
static unsigned receipt_owner;
static GuestPadRead *receipt_rows;
static GuestLatchRead *latch_rows;
static size_t receipt_count;
static int receipt_alloc_refused;
static const char *receipt_terminal;

/* The pad lock may acquire this lock last; the renderer acquires only this lock. */
static HostMutex latch_lock = HOST_MUTEX_INIT;
static atomic_int latch_enabled;
static uint64_t latch_nonce, latch_command;
/* Read and updated only by the native pad owner under the existing pad lock. */
static const char *heartbeat_path;
static uint64_t next_heartbeat_poll;
static int heartbeat_finished;
static struct {
    BbSewerPadKey key;
    BbSewerPadStatus status;
    uint64_t read, clean_clear_ns, active_read, arm_read;
    uint64_t host_deadline, render_deadline, absolute_deadline;
    unsigned read_owner;
    int heartbeat_valid;
} latch;

/* Request-scoped copies under latch_lock. Printing always happens after the caller unlocks. */
static int boundary_enabled, pc_rest_enabled;
typedef struct {
    int gate, opened, disk, length, separators, matched;
    uint64_t nonce, command, counter;
} BoundaryBeat;
typedef struct {
    uint64_t read, now, observed, clean_ns, host_until, heartbeat;
    unsigned owner, current, receipt_owner, receipts, gamepads, flags;
    int sampled, clean, clear, before_rx, clean_owner, polled, valid, phase;
    const char *terminal;
    PadData pre, final;
    PadScriptReceipt script;
    BoundaryBeat beat;
    BbPcRestWitness pc;
    uint8_t pc_rest;
} BoundaryRead;
enum {
    B_FIRST = 1, B_NEUTRAL = 2, B_TAGGED = 4, B_QUALIFIED = 8, B_POLL = 16, B_MATCHED = 32, B_NO_ARM_750MS = 64,
    B_ROWS = 1, B_LATCH_ROWS = 2, B_OOM = 4
};
typedef struct {
    BbSewerPadKey key;
    BbSewerPadStatus status;
    uint64_t read, now, clean_ns, host_until, render_until, absolute_until;
    unsigned current, read_owner, attempt;
    int heartbeat_valid, reached, predicate;
    const char *reason;
} BoundaryArm;
static struct {
    BoundaryRead last, poll, transition;
    BoundaryArm last_arm;
    unsigned reads, milestones, attempts;
    uint64_t first_arm_ns, first_tagged_ns;
    int mature, dumped;
} boundary;

static void pc_rest_fields(char suffix[128], const BbPcRestWitness *pc, unsigned rest) {
    *suffix = 0;
    if (!pc_rest_enabled) return;
    snprintf(suffix, 128, " pc_branch=%u pc_external=%08" PRIx32
             " pc_before=%u,%u,%u,%u,%u,%u,%u,%u,%08" PRIx32 " pc_rest=%u",
             pc->branch, pc->external, pc->present, pc->lx, pc->ly, pc->rx, pc->ry,
             pc->l2, pc->r2, pc->touch_count, pc->buttons, rest);
}

static void boundary_read_log(const char *sample, const BoundaryRead *r, unsigned first) {
    if (!r->read) return;
    const PadData *a = &r->pre, *b = &r->final;
    char suffix[128];
    pc_rest_fields(suffix, &r->pc, r->pc_rest);
    printf("[sewer-pad-probe] event=read request=%" PRIu64 " command=%016" PRIx64
           " sample=%s first_flags=%u read=%" PRIu64 " ns=%" PRIu64 " phase=%d gamepads=%u"
           " pre=%u,%u,%u,%u,%u,%u,%u,%u,%08" PRIx32 " final=%u,%u,%u,%u,%u,%u,%u,%u,%08" PRIx32
           " owner=%u current=%u receipt_owner=%u receipts=%u buffers=%u terminal=%s"
           " sampled=%d replay=%d healthy=%d kind=%d script_gen=%" PRIu64 " tag_gen=%" PRIu64
           " observed=%016" PRIx64 " script_axes=%d,%d,%d,%d clean=%d clear=%d before_rx=%d clean_owner=%d"
           " polled=%d beat_gate=%d beat_open=%d beat_disk=%d beat_len=%d beat_slashes=%d beat_match=%d"
           " beat_nonce=%016" PRIx64 " beat_command=%016" PRIx64 " beat_counter=%016" PRIx64
           " heartbeat_valid=%d heartbeat=%016" PRIx64 " clean_ns=%" PRIu64 " host_until=%" PRIu64 "%s\n",
           latch_nonce, latch_command, sample, first, r->read, r->now, r->phase, r->gamepads,
           a->connected, a->left_x, a->left_y, a->right_x, a->right_y, a->l2, a->r2, a->touch_count, a->buttons,
           b->connected, b->left_x, b->left_y, b->right_x, b->right_y, b->l2, b->r2, b->touch_count, b->buttons,
           r->owner, r->current, r->receipt_owner, r->receipts, r->flags, r->terminal ? r->terminal : "none",
           r->sampled, r->script.replay_state, r->script.healthy_file, r->script.kind, r->script.native_generation,
           r->script.command_generation, r->observed, r->script.axes[0], r->script.axes[1], r->script.axes[2],
           r->script.axes[3], r->clean, r->clear, r->before_rx, r->clean_owner, r->polled, r->beat.gate, r->beat.opened,
           r->beat.disk, r->beat.length, r->beat.separators, r->beat.matched, r->beat.nonce, r->beat.command,
           r->beat.counter, r->valid, r->heartbeat, r->clean_ns, r->host_until, suffix);
}

static void boundary_arm_log(const char *sample, const BoundaryArm *a) {
    if (!a->attempt) return;
    printf("[sewer-pad-probe] event=arm request=%" PRIu64 " command=%016" PRIx64
           " sample=%s frame=%" PRIu32 " scene=%" PRIu64 " loading=%" PRIu64 " generation=%" PRIu64
           " attempt=%u ns=%" PRIu64 " read=%" PRIu64 " current=%u read_owner=%u"
           " reason=%s reached=%d predicate=%d phase=%d fault=%d heartbeat_valid=%d heartbeat=%016" PRIx64
           " clean_ns=%" PRIu64 " host_until=%" PRIu64 " render_until=%" PRIu64
           " absolute_until=%" PRIu64 "\n",
           latch_nonce, latch_command, sample, a->key.frame, a->key.scene, a->key.loading, a->key.generation,
           a->attempt, a->now, a->read, a->current, a->read_owner, a->reason, a->reached, a->predicate,
           a->status.phase, a->status.fault, a->heartbeat_valid, a->status.heartbeat, a->clean_ns,
           a->host_until, a->render_until, a->absolute_until);
}

typedef struct {
    unsigned reads, arms;
    BoundaryRead last, poll, transition;
    BoundaryArm arm;
    BbSewerPadStatus status;
} BoundarySummary;

/* Called inside the existing latch lock. The caller prints from this copy after unlock. */
static int boundary_capture_summary(BoundarySummary *summary) {
    if (!boundary_enabled || boundary.dumped) return 0;
    boundary.dumped = 1;
    *summary = (BoundarySummary){boundary.reads, boundary.attempts, boundary.last, boundary.poll,
                                boundary.transition, boundary.last_arm, latch.status};
    return 1;
}

static void boundary_summary_log(const BoundarySummary *s) {
    printf("[sewer-pad-probe] event=summary request=%" PRIu64 " command=%016" PRIx64
           " reason=cancel reads=%u arms=%u phase=%d fault=%d\n",
           latch_nonce, latch_command, s->reads, s->arms, s->status.phase, s->status.fault);
    boundary_read_log("last", &s->last, 0);
    boundary_read_log("last-poll", &s->poll, 0);
    boundary_read_log("last-transition", &s->transition, 0);
    boundary_arm_log("last", &s->arm);
}

static const uint64_t HEARTBEAT_POLL_NS = UINT64_C(20000000);
static const uint64_t LATCH_HOST_NS = UINT64_C(500000000);
static const uint64_t LATCH_RENDER_NS = UINT64_C(250000000);
static const uint64_t LATCH_ABSOLUTE_NS = UINT64_C(3000000000);

static uint64_t latch_hex(const char *text) {
    if (!text || strlen(text) != 16 || strspn(text, "0123456789abcdef") != 16) return 0;
    return strtoull(text, NULL, 16);
}

static void latch_init(const char *nonce) {
    const char *mode = getenv("BB_SEWER_PAD_LATCH");
    if (!mode || strcmp(mode, "1")) return;
    latch_command = latch_hex(getenv("BB_SEWER_PAD_LATCH_COMMAND"));
    if (!latch_command) return;
    latch_nonce = latch_hex(nonce);
    heartbeat_path = getenv("BB_SEWER_PAD_HEARTBEAT_PATH");
    const char *trace = getenv("BB_SEWER_PAD_BOUNDARY");
    boundary_enabled = trace && !strcmp(trace, "1");
    const char *pc_rest = getenv("BB_SEWER_PAD_PC_REST");
    pc_rest_enabled = boundary_enabled && latch_command == 6 && pc_rest && !strcmp(pc_rest, "1");
    atomic_store_explicit(&latch_enabled, 1, memory_order_release);
}

static int latch_is_enabled(void) {
    return atomic_load_explicit(&latch_enabled, memory_order_acquire);
}

static int latch_active(void) { return latch.status.phase == BB_SEWER_PAD_ARMED; }
static int latch_spent(void) { return latch.status.stop_serial != 0; }

static void latch_cut(BbSewerPadCause cause) {
    if (!latch_spent()) {
        /* A launch owns one command generation. Its first cut is its only stop event. */
        latch.status.stop_serial = 1;
        latch.status.after_read = latch.read;
        latch.status.stop_loading = latch.key.loading;
        latch.status.stop_generation = latch.key.generation;
        latch.status.stop_frame = latch.key.frame;
        latch.status.stop_scene = latch.key.scene;
        latch.status.stop_cause = cause;
        latch.status.phase = BB_SEWER_PAD_CUT;
    }
    if (cause != BB_SEWER_PAD_PROJECTION) {
        if (!latch.status.fault) latch.status.fault = cause;
        latch.status.phase = BB_SEWER_PAD_REFUSED;
    }
}

static void latch_expire(uint64_t now) {
    if (!latch_active()) return;
    if (now >= latch.absolute_deadline) latch_cut(BB_SEWER_PAD_ABSOLUTE);
    else if (now >= latch.host_deadline) latch_cut(BB_SEWER_PAD_HOST_LEASE);
    else if (now >= latch.render_deadline) latch_cut(BB_SEWER_PAD_RENDER_LEASE);
}

BbSewerPadStatus bbgpu_sewer_pad_latch(BbSewerPadAction action, const BbSewerPadKey *key) {
    const BbSewerPadStatus refused = {.phase = BB_SEWER_PAD_REFUSED,
                                      .fault = BB_SEWER_PAD_PUBLICATION};
    if (!latch_is_enabled() || !key || key->request != latch_nonce ||
        key->command != latch_command || !key->scene) return refused;
    host_lock(&latch_lock);
    if (latch.key.request && (latch.key.loading != key->loading ||
                             latch.key.generation != key->generation)) {
        host_unlock(&latch_lock);
        return refused;
    }
    const uint64_t now = host_monotonic_ns();
    const int trace_arm = boundary_enabled && action == BB_SEWER_PAD_ARM;
    int reached = 0, predicate = 0;
    unsigned current = 0;
    const char *reason = "spent";
    latch_expire(now);
    if (latch_active() && latch.status.owner != atomic_load_explicit(&owner_generation, memory_order_acquire))
        latch_cut(BB_SEWER_PAD_OWNER);
    if (action == BB_SEWER_PAD_CANCEL) {
        if (latch.key.request) latch_cut(BB_SEWER_PAD_CANCELLED);
    } else if (!latch_spent()) {
        if (latch.key.request && (key->scene <= latch.key.scene || key->frame < latch.key.frame)) {
            reason = "sequence";
            latch_cut(BB_SEWER_PAD_PUBLICATION);
        } else {
            latch.key = *key;
            if (latch_active()) {
                reason = "already-active";
                latch.render_deadline = now + LATCH_RENDER_NS;
                if (action == BB_SEWER_PAD_STOP) {
                    latch_cut(latch.active_read && latch.active_read == latch.read
                                  ? BB_SEWER_PAD_PROJECTION : BB_SEWER_PAD_INPUT);
                }
            } else if (action == BB_SEWER_PAD_ARM) {
                reached = 1;
                reason = "predicate";
                const int fresh = latch.heartbeat_valid && now < latch.host_deadline &&
                    latch.clean_clear_ns && now >= latch.clean_clear_ns &&
                    now - latch.clean_clear_ns < LATCH_RENDER_NS;
                if (fresh || trace_arm)
                    current = atomic_load_explicit(&owner_generation, memory_order_acquire);
                predicate = fresh && latch.read_owner == current;
                if (predicate) {
                    latch.status.phase = BB_SEWER_PAD_ARMED;
                    latch.status.owner = latch.read_owner;
                    latch.arm_read = latch.read;
                    latch.absolute_deadline = now + LATCH_ABSOLUTE_NS;
                    latch.render_deadline = now + LATCH_RENDER_NS;
                }
            }
        }
    }
    const BbSewerPadStatus status = latch.status;
    const char *emit = NULL;
    BoundaryArm observed;
    BoundaryRead reads[3];
    if (trace_arm) {
        if (!reached) current = atomic_load_explicit(&owner_generation, memory_order_acquire);
        observed = (BoundaryArm){.key = *key, .status = status, .now = now, .read = latch.read,
            .clean_ns = latch.clean_clear_ns, .host_until = latch.host_deadline, .render_until = latch.render_deadline,
            .absolute_until = latch.absolute_deadline, .current = current, .read_owner = latch.read_owner,
            .attempt = ++boundary.attempts, .heartbeat_valid = latch.heartbeat_valid,
            .reached = reached, .predicate = predicate, .reason = reason};
        boundary.last_arm = observed;
        if (observed.attempt == 1) {
            boundary.first_arm_ns = now;
            emit = "first";
        } else if (pc_rest_enabled && predicate) {
            emit = "armed";
        } else if (!boundary.mature && status.phase == BB_SEWER_PAD_WAITING &&
                   now - boundary.first_arm_ns >= UINT64_C(750000000)) {
            boundary.mature = 1;
            emit = "idle-750ms";
        }
        if (emit) {
            reads[0] = boundary.last;
            reads[1] = boundary.poll;
            reads[2] = boundary.transition;
        }
    }
    BoundarySummary summary;
    const int report = action == BB_SEWER_PAD_CANCEL && boundary_capture_summary(&summary);
    host_unlock(&latch_lock);
    if (emit) {
        boundary_arm_log(emit, &observed);
        boundary_read_log("at-arm-last", &reads[0], 0);
        boundary_read_log("at-arm-poll", &reads[1], 0);
        boundary_read_log("at-arm-transition", &reads[2], 0);
    }
    if (report) boundary_summary_log(&summary);
    return status;
}

/* Open the Worker publication once; a concurrent atomic replace cannot mix two snapshots. */
static int heartbeat_bytes(char wire[51], BoundaryBeat *beat) {
#ifdef _WIN32
    HANDLE file = CreateFileA(heartbeat_path, GENERIC_READ,
                              FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                              NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) return 0;
    DWORD size = 0;
    const int disk = GetFileType(file) == FILE_TYPE_DISK;
    const int ok = disk && ReadFile(file, wire, 51, &size, NULL);
    CloseHandle(file);
    if (beat) {
        beat->opened = 1;
        beat->disk = disk;
        beat->length = ok ? (int)size : -1;
    }
    return ok && size == 50;
#else
    const int file = open(heartbeat_path, O_RDONLY | O_NONBLOCK);
    if (file < 0) return 0;
    struct stat info;
    const int disk = !fstat(file, &info) && S_ISREG(info.st_mode);
    const ssize_t size = disk ? read(file, wire, 51) : -1;
    close(file);
    if (beat) {
        beat->opened = 1;
        beat->disk = disk;
        beat->length = (int)size;
    }
    return size == 50;
#endif
}

static int poll_heartbeat(uint64_t *counter, BoundaryBeat *beat) {
    if (heartbeat_finished || !heartbeat_path || !*heartbeat_path) {
        if (beat) beat->gate = heartbeat_finished ? 1 : 2;
        return 0;
    }
    const uint64_t now = host_monotonic_ns();
    if (now < next_heartbeat_poll) {
        if (beat) beat->gate = 3;
        return 0;
    }
    if (beat) beat->gate = 4;
    next_heartbeat_poll = now + HEARTBEAT_POLL_NS;
    char wire[51];
    if (heartbeat_bytes(wire, beat) && wire[16] == '/' && wire[33] == '/') {
        wire[16] = wire[33] = wire[50] = '\0';
        const uint64_t nonce = latch_hex(wire);
        const uint64_t command = (nonce == latch_nonce || beat) ? latch_hex(wire + 17) : 0;
        const int matched = nonce == latch_nonce && command == latch_command;
        const uint64_t parsed = (matched || beat) ? latch_hex(wire + 34) : 0;
        if (matched) *counter = parsed;
        if (beat) {
            beat->separators = 1;
            beat->matched = matched;
            beat->nonce = nonce;
            beat->command = command;
            beat->counter = parsed;
        }
    }
    return 1;
}

static int latch_other_inputs_clean(const PadData *pad) {
    return pad->connected && !pad->buttons && pad->left_x == 128 && pad->left_y == 128 &&
           pad->right_y == 128 && !pad->l2 && !pad->r2 && !pad->touch_count;
}

static int pc_rest_clean(const BbPcRestWitness *pc, const PadData *pre, const PadData *final, int sampled,
                         int active_rx, const PadScriptReceipt *script) {
    if (!sampled || !pc->present || pc->external ||
        (pc->branch != BB_PC_REST_INACTIVE && pc->branch != BB_PC_REST_KEYBOARD) ||
        pc->lx != 128 || pc->ly != 128 || pc->rx != 128 || pc->ry != 128 ||
        pc->buttons || pc->l2 || pc->r2 || pc->touch_count) return 0;
    if (!pre->connected || pre->buttons || pre->l2 || pre->r2 || pre->touch_count ||
        pre->left_x != 127 || pre->left_y != 127 || pre->right_x != 127 || pre->right_y != 127) return 0;
    return final->connected && !final->buttons && !final->l2 && !final->r2 && !final->touch_count &&
        final->left_x == 127 && final->left_y == 127 && final->right_y == 127 &&
        (active_rx ? script->axes[2] == 80 && final->right_x == 80 : final->right_x == 127);
}

static BbSewerPadStatus latch_return(const PadData *pre, PadData *final, int sampled_script,
                                     unsigned owner, GuestLatchRead *detail,
                                     BoundaryRead *probe, unsigned *emit_probe) {
    const PadScriptReceipt script = pad_script_receipt();
    detail->observed_command = sampled_script ? pad_script_observed_command() : 0;
    const int exact_rx = sampled_script && !script.replay_state && detail->observed_command == latch_command &&
                         script.axes[2] >= 0 && final->right_x == script.axes[2];
    const int active_rx = exact_rx && script.kind == PAD_RECEIPT_RX && script.healthy_file &&
                          script.command_generation == latch_command && script.axes[2] != 128;
    const int stock_clean = pre->right_x == 128 && latch_other_inputs_clean(pre) && latch_other_inputs_clean(final);
    if (pc_rest_enabled && !stock_clean && pc_rest_clean(&detail->pc, pre, final, sampled_script, active_rx, &script))
        detail->pc_rest = 127;
    const int clean = stock_clean || detail->pc_rest;
    const int clear = sampled_script && !script.replay_state && script.healthy_file &&
                      (script.kind == PAD_RECEIPT_CLEAR || script.kind == PAD_RECEIPT_FINISH) &&
                      final->right_x == pre->right_x;
    const unsigned current = ((owner & 1) || probe) ?
        atomic_load_explicit(&owner_generation, memory_order_acquire) : 0;
    const int local_owner = (owner & 1) && owner == current;
    const int before_rx = clear && script.kind == PAD_RECEIPT_CLEAR && script.command_generation < latch_command;
    const int clean_owner = clean && local_owner && receipt_rows && latch_rows && owner == receipt_owner;
    uint64_t counter = 0;
    BoundaryBeat beat = {.length = -1};
    const int polled = clean_owner && (before_rx || active_rx) && poll_heartbeat(&counter, probe ? &beat : NULL);
    host_lock(&latch_lock);
    const uint64_t now = host_monotonic_ns();
    latch_expire(now);
    if ((latch_active() || latch.status.phase == BB_SEWER_PAD_CUT) &&
        (!local_owner || owner != latch.status.owner)) latch_cut(BB_SEWER_PAD_OWNER);
    if (latch_active() || latch.status.phase == BB_SEWER_PAD_CUT) {
        if (receipt_count + 1 >= PAD_RECEIPT_MAX || reads - latch.arm_read >= PAD_RECEIPT_MAX ||
            receipt_alloc_refused || receipt_terminal) latch_cut(BB_SEWER_PAD_BUDGET);
        else if (!clean) latch_cut(BB_SEWER_PAD_INPUT);
    }
    if (latch_active()) {
        if (active_rx) latch.active_read = reads;
        else if (!(clear && script.command_generation < latch_command && !latch.active_read))
            latch_cut(exact_rx ? BB_SEWER_PAD_PUBLICATION : BB_SEWER_PAD_INPUT);
    } else if (!latch_spent() && exact_rx) {
        latch_cut(BB_SEWER_PAD_EARLY_RX);
    }
    if (polled && !latch_spent()) {
        latch.heartbeat_valid = counter && counter >= latch.status.heartbeat;
        if (counter > latch.status.heartbeat) {
            latch.status.heartbeat = counter;
            latch.host_deadline = now + LATCH_HOST_NS;
        }
    }
    heartbeat_finished = latch_spent();
    latch.clean_clear_ns = clean_owner && before_rx ? now : 0;
    latch.read_owner = owner;
    if (latch_spent() && exact_rx) {
        final->right_x = pre->right_x;
        detail->inherited_rx = 1;
    }
    if (latch.status.phase == BB_SEWER_PAD_CUT &&
        !(active_rx || (clear && script.command_generation > latch_command)))
        latch_cut(BB_SEWER_PAD_PUBLICATION);
    if (latch_spent() && !latch.status.first_read) {
        latch.status.first_read = reads;
        latch.status.first_inherited = detail->inherited_rx;
    }
    latch.read = reads;
    const BbSewerPadStatus status = latch.status;
    if (probe) {
        const unsigned buffers = (receipt_rows ? B_ROWS : 0) | (latch_rows ? B_LATCH_ROWS : 0) |
                                 (receipt_alloc_refused ? B_OOM : 0);
        *probe = (BoundaryRead){.read = reads, .now = now, .observed = detail->observed_command, .clean_ns = latch.clean_clear_ns,
            .host_until = latch.host_deadline, .heartbeat = status.heartbeat, .owner = owner, .current = current,
            .receipt_owner = receipt_owner, .receipts = (unsigned)receipt_count, .gamepads = pad_host_connected_count(),
            .flags = buffers, .sampled = sampled_script, .clean = clean, .clear = clear, .before_rx = before_rx,
            .clean_owner = clean_owner, .polled = polled, .valid = latch.heartbeat_valid, .phase = status.phase,
            .terminal = receipt_terminal, .pre = *pre, .final = *final, .script = script, .beat = beat,
            .pc = detail->pc, .pc_rest = detail->pc_rest};
        const BoundaryRead *p = &boundary.last;
        if (p->owner != owner || p->current != current || p->receipt_owner != receipt_owner || p->flags != buffers ||
            p->sampled != sampled_script || p->script.kind != script.kind || p->script.healthy_file != script.healthy_file ||
            p->script.replay_state != script.replay_state || p->script.command_generation != script.command_generation ||
            p->clean != clean || p->clear != clear || p->clean_owner != clean_owner || p->valid != latch.heartbeat_valid ||
            p->phase != (int)status.phase || p->terminal != receipt_terminal || p->pc_rest != detail->pc_rest ||
            p->pc.branch != detail->pc.branch || p->pc.external != detail->pc.external)
            boundary.transition = *probe;
        if (polled) boundary.poll = *probe;
        boundary.last = *probe;
        unsigned seen = (!boundary.reads++ ? B_FIRST : 0) |
            (pre->right_x == 128 && latch_other_inputs_clean(pre) ? B_NEUTRAL : 0) |
            (sampled_script && script.kind == PAD_RECEIPT_CLEAR && script.command_generation ? B_TAGGED : 0) |
            (clean_owner && before_rx ? B_QUALIFIED : 0) | (polled ? B_POLL : 0) |
            (beat.matched && counter && latch.heartbeat_valid ? B_MATCHED : 0);
        if ((seen & B_TAGGED) && !boundary.first_tagged_ns) boundary.first_tagged_ns = now;
        if (!boundary.attempts && boundary.first_tagged_ns &&
            now - boundary.first_tagged_ns >= UINT64_C(750000000)) seen |= B_NO_ARM_750MS;
        *emit_probe = seen & ~boundary.milestones;
        boundary.milestones |= seen;
    }
    host_unlock(&latch_lock);
    return status;
}

static void receipt_init(void) {
    const char *nonce = getenv("BB_SEWER_PAD_RECEIPT");
    const char *path = getenv("BB_SEWER_PAD_RECEIPT_PATH");
    if (!nonce || strlen(nonce) != 16 || strspn(nonce, "0123456789abcdef") != 16 ||
        !strcmp(nonce, "0000000000000000") || !path || !*path) return;
    receipt_path = malloc(strlen(path) + 1);
    if (!receipt_path) return;
    memcpy(receipt_path, path, strlen(path) + 1);
    memcpy(receipt_nonce, nonce, sizeof(receipt_nonce));
    atomic_store_explicit(&receipt_enabled, 1, memory_order_release);
    latch_init(nonce);
}

const char *pad_guest_receipt_nonce(void) {
    return atomic_load_explicit(&receipt_enabled, memory_order_acquire) ? receipt_nonce : NULL;
}

static int receipt_observe(const PadData *pre, const PadData *final, int sampled_script, unsigned owner,
                           const GuestLatchRead *latch_row) {
    if (receipt_terminal) return 0;
    if (receipt_count == PAD_RECEIPT_MAX) {
        receipt_terminal = "cap";
        return 1;
    }
    PadScriptReceipt script = pad_script_receipt();
    if (!sampled_script) script.kind = PAD_RECEIPT_OVERLAY;
    else if (!script.healthy_file) script.kind = PAD_RECEIPT_FILE_ERROR;
    const int local_owner = (owner & 1) &&
                             owner == atomic_load_explicit(&owner_generation, memory_order_acquire);
    if (!receipt_rows && !receipt_alloc_refused && local_owner && !script.replay_state &&
        (script.kind == PAD_RECEIPT_RX || script.kind == PAD_RECEIPT_CLEAR)) {
        receipt_rows = calloc(PAD_RECEIPT_MAX, sizeof(*receipt_rows));
        if (receipt_rows && latch_row) latch_rows = calloc(PAD_RECEIPT_MAX, sizeof(*latch_rows));
        receipt_alloc_refused = !receipt_rows || (latch_row && !latch_rows);
        receipt_owner = owner;
    }
    if (!receipt_rows) return 0;
    if (latch_rows && latch_row) latch_rows[receipt_count] = *latch_row;
    GuestPadRead *row = &receipt_rows[receipt_count++];
    row->serial = reads;
    row->monotonic_ns = host_monotonic_ns();
    row->owner_generation = owner;
    row->owner_ok = local_owner && owner == receipt_owner;
    row->script = script;
    memcpy(&row->pre, pre, sizeof(*pre));
    memcpy(&row->final, final, sizeof(*final));
    if (script.kind == PAD_RECEIPT_FINISH) {
        receipt_terminal = "finish";
        return 1;
    }
    return 0;
}

static void receipt_bytes(FILE *file, const PadData *pad) {
    const unsigned char *bytes = (const unsigned char *)pad;
    char hex[sizeof(*pad) * 2];
    static const char digits[] = "0123456789abcdef";
    for (size_t i = 0; i < sizeof(*pad); ++i) {
        hex[2 * i] = digits[bytes[i] >> 4];
        hex[2 * i + 1] = digits[bytes[i] & 15];
    }
    fwrite(hex, 1, sizeof(hex), file);
}

static void receipt_report(void) {
    /* The read path freezes the bounded buffer first. No pad lock is held during I/O. */
    FILE *file = fopen(receipt_path, "wbx");
    if (!file) {
        printf("[sewer-pad] receipt=unavailable nonce=%s why=open\n", receipt_nonce);
        return;
    }
    fprintf(file, "sewer-pad-v1 nonce=%s count=%zu terminal=%s oom=%d handle=%d\n",
            receipt_nonce, receipt_count, receipt_terminal, receipt_alloc_refused, THE_HANDLE);
    for (size_t i = 0; i < receipt_count; ++i) {
        const GuestPadRead *row = &receipt_rows[i];
        const PadScriptReceipt *script = &row->script;
        fprintf(file, "read serial=%" PRIu64 " ns=%" PRIu64 " owner_gen=%u owner_ok=%d"
                " parse=%" PRIu64 " command=%016" PRIx64 " kind=%d file_ok=%d replay=%d"
                " buttons=%08" PRIx32 " axes=%d,%d,%d,%d touch=%d pre=",
                row->serial, row->monotonic_ns, row->owner_generation, row->owner_ok,
                script->native_generation, script->command_generation, (int)script->kind,
                script->healthy_file, script->replay_state, script->buttons,
                script->axes[0], script->axes[1], script->axes[2], script->axes[3], script->touch_side);
        receipt_bytes(file, &row->pre);
        fputs(" final=", file);
        receipt_bytes(file, &row->final);
        if (latch_rows) {
            const GuestLatchRead *detail = &latch_rows[i];
            const BbSewerPadStatus *cut = &detail->status;
            fprintf(file, " latch_phase=%d stop=%" PRIu64 " stop_cause=%d fault=%d"
                    " stop_loading=%" PRIu64 " stop_generation=%" PRIu64 " stop_command=%016" PRIx64
                    " stop_frame=%" PRIu32 " stop_scene=%" PRIu64 " stop_after=%" PRIu64
                    " first_after=%" PRIu64 " first_inherited=%d observed=%016" PRIx64
                    " rx_inherited=%d heartbeat=%016" PRIx64,
                    cut->phase, cut->stop_serial, cut->stop_cause, cut->fault, cut->stop_loading,
                    cut->stop_generation, cut->stop_serial ? latch_command : 0, cut->stop_frame,
                    cut->stop_scene, cut->after_read, cut->first_read, cut->first_inherited,
                    detail->observed_command, detail->inherited_rx, cut->heartbeat);
            if (pc_rest_enabled) {
                char suffix[128];
                pc_rest_fields(suffix, &detail->pc, detail->pc_rest);
                fputs(suffix, file);
            }
        }
        fputc('\n', file);
    }
    fprintf(file, "end count=%zu\n", receipt_count);
    const int failed = ferror(file);
    if (fclose(file) || failed)
        printf("[sewer-pad] receipt=unavailable nonce=%s why=write\n", receipt_nonce);
    else
        printf("[sewer-pad] receipt=written nonce=%s count=%zu terminal=%s\n",
               receipt_nonce, receipt_count, receipt_terminal);
}

uint64_t pad_now_us(void) {
    return host_monotonic_ns() / 1000;
}

void pad_touch_click(PadData *pad, int right_half) {
    pad->buttons |= PAD_TOUCHPAD;
    pad->touch_count = 1;
    pad->touches[0] = (PadTouch){.x = right_half ? 1440 : 480, .y = 471, .id = 0};
}

static void number_touches(PadData *pad) {
    static uint8_t next = 1, ids[2];
    static int down[2];
    static uint64_t first_down;
    for (int i = 0; i < 2; ++i) {
        int touching = i < pad->touch_count;
        if (touching && !down[i]) {
            ids[i] = next;
            next = next == 127 ? 1 : next + 1;
        }
        down[i] = touching;
        if (touching) pad->touches[i].id = ids[i];
    }
    if (!pad->touch_count) first_down = 0;
    else if (!first_down) first_down = pad->timestamp;
    pad->touch_held_time = pad->touch_count ? (uint32_t)(pad->timestamp - first_down) : 0;
}

static int sample(PadData *pad, PadData *pre, BbPcRestWitness *pc) {
    pad_host_sample(pad, pc);
    if (pre) memcpy(pre, pad, sizeof(*pre));
    if (bbgpu_overlay_captures_input()) {
        if (pc) pc->external |= BB_PC_REST_OVERLAY;
        holding_after_overlay = 1;
        return 0;
    }
    pad_script_record(pad);
    pad_script_buttons(pad);
    if (holding_after_overlay) {
        if (pad->buttons) {
            pad->buttons = 0;
            pad->l2 = pad->r2 = 0;
        } else {
            holding_after_overlay = 0;
        }
    }
    pad_script_overrides(pad);
    number_touches(pad);
    return 1;
}

static int handle_ok(int32_t handle) {
    return handle == THE_HANDLE && opened;
}

static SYS_ABI int32_t pad_init(void) {
    host_lock(&lock);
    if (!initialized) receipt_init();
    initialized = 1;
    host_unlock(&lock);
    return 0;
}

static SYS_ABI int32_t pad_open(int32_t user, int32_t type, int32_t index, const void *param) {
    (void)param;
    if (!initialized) return PAD_ERROR_NOT_INITIALIZED;
    if (user != THE_USER || (type != PAD_TYPE_STANDARD && type != PAD_TYPE_SPECIAL) || index) return PAD_ERROR_ARGUMENT;
    host_lock(&lock);
    int was_open = opened;
    opened = 1;
    if (pad_guest_receipt_nonce() && !was_open)
        atomic_fetch_add_explicit(&owner_generation, 1, memory_order_release);
    host_unlock(&lock);
    if (was_open) return PAD_ERROR_OPENED;
    puts("Runtime: pad opened for user 1 (SDL gamepad or keyboard)");
    return THE_HANDLE;
}

static SYS_ABI int32_t pad_close(int32_t handle) {
    const int latched = latch_is_enabled();
    if (latched) host_lock(&lock);
    const int ok = handle_ok(handle);
    if (ok) {
        if (pad_guest_receipt_nonce()) atomic_fetch_add_explicit(&owner_generation, 1, memory_order_release);
        opened = 0;
    }
    if (latched) host_unlock(&lock);
    return ok ? 0 : PAD_ERROR_HANDLE;
}

static SYS_ABI int32_t pad_read_state(int32_t handle, PadData *pad) {
    const int enabled = pad_guest_receipt_nonce() != NULL;
    const int latched = enabled && latch_is_enabled();
    const unsigned owner = enabled ? atomic_load_explicit(&owner_generation, memory_order_acquire) : 0;
    if (handle != THE_HANDLE || (!latched && !handle_ok(handle))) return PAD_ERROR_HANDLE;
    if (!pad) return PAD_ERROR_ARGUMENT;
    bbgpu_anti_lag_before_input();
    host_lock(&lock);
    PadData pre;
    if (latched && !handle_ok(handle)) {
        host_unlock(&lock);
        return PAD_ERROR_HANDLE;
    }
    const int wanted = enabled && !receipt_terminal && receipt_count < PAD_RECEIPT_MAX;
    GuestLatchRead detail;
    if (latched) detail = (GuestLatchRead){0};
    const int sampled_script = sample(pad, wanted || latched ? &pre : NULL,
                                      latched && pc_rest_enabled ? &detail.pc : NULL);
    bbgpu_spark_probe_pad(pad->buttons); /* bbport (r108_spark-probe, TOOL): BB_SPARK_PROBE=1 only */
    bbgpu_weapon_sparks_pad(pad->buttons); /* bbport (r110_weapon-sparks): BB_WEAPON_SPARKS only */
    ++reads;
    int emit_receipt = 0;
    unsigned emit_probe = 0;
    BoundaryRead probe;
    if (latched) {
        detail.status = latch_return(&pre, pad, sampled_script, owner, &detail,
                                     boundary_enabled ? &probe : NULL, &emit_probe);
        emit_receipt = receipt_observe(&pre, pad, sampled_script, owner, &detail);
    } else if (enabled) {
        emit_receipt = receipt_observe(&pre, pad, sampled_script, owner, NULL);
    }
    host_unlock(&lock);
    if (emit_probe) boundary_read_log("first-milestone", &probe, emit_probe);
    if (emit_receipt) receipt_report();
    return 0;
}

static SYS_ABI int32_t pad_get_controller_information(int32_t handle, PadControllerInfo *info) {
    if (!handle_ok(handle)) return PAD_ERROR_HANDLE;
    if (!info) return PAD_ERROR_ARGUMENT;
    memset(info, 0, sizeof(*info));
    info->pixel_density = 44.86f;
    info->resolution_x = PAD_TOUCH_WIDTH;
    info->resolution_y = PAD_TOUCH_HEIGHT;
    info->dead_zone_left = info->dead_zone_right = 2;
    info->connected = 1;
    host_lock(&lock);
    pad_host_refresh();
    uint8_t count = pad_host_connected_count();
    info->connected_count = count ? count : 1;
    host_unlock(&lock);
    return 0;
}

static SYS_ABI int32_t pad_set_vibration(int32_t handle, const uint8_t *motors) {
    if (!handle_ok(handle)) return PAD_ERROR_HANDLE;
    if (!motors) return PAD_ERROR_ARGUMENT;
    host_lock(&lock);
    pad_host_rumble(motors[0], motors[1]);
    host_unlock(&lock);
    return 0;
}

static SYS_ABI int32_t pad_accept(int32_t handle) {
    return handle_ok(handle) ? 0 : PAD_ERROR_HANDLE;
}

static SYS_ABI int32_t pad_accept_flag(int32_t handle, uint8_t flag) {
    (void)flag;
    return pad_accept(handle);
}

void sys_pad_lock(void) {
    host_lock(&lock);
}

void sys_pad_unlock(void) {
    host_unlock(&lock);
}

void sys_pad_report(void) {
    printf("Runtime: pad reads=%zu, gamepad=%s\n", reads, pad_host_gamepad_name());
    if (pad_guest_receipt_nonce()) {
        host_lock(&lock);
        const int emit_receipt = !receipt_terminal;
        if (emit_receipt) receipt_terminal = "shutdown";
        host_unlock(&lock);
        if (emit_receipt) receipt_report();
    }
}

static const SysExport exports[] = {
    {"6ncge5+l5Qs", "scePadClose", pad_close},
    {"gjP9-KQzoUk", "scePadGetControllerInformation", pad_get_controller_information},
    {"hv1luiJrqQM", "scePadInit", pad_init},
    {"xk0AcarP3V4", "scePadOpen", pad_open},
    {"YndgXqQVV7c", "scePadReadState", pad_read_state},
    {"rIZnR6eSpvk", "scePadResetOrientation", pad_accept},
    {"r44mAxdSG+U", "scePadSetAngularVelocityDeadbandState", pad_accept_flag},
    {"vDLMoJLde8I", "scePadSetTiltCorrectionState", pad_accept_flag},
    {"yFVnOdGxvZY", "scePadSetVibration", pad_set_vibration},
};

SYS_LIBRARY(sys_pad, "libScePad", exports);
