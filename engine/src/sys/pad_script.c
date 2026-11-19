// SPDX-License-Identifier: GPL-3.0-or-later
#include "pad.h"
#include <SDL3/SDL.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif

typedef struct {
    uint32_t ms, buttons;
    uint8_t axes[4], l2, r2;
} PadSample;

enum { REPLAY_OFF, REPLAY_RUNNING, REPLAY_DONE };

static struct {
    uint32_t buttons;
    int stick[4];
    int touch_side;
} injected = {0, {-1, -1, -1, -1}, -1};

static int replay_state;
/* Both snapshots and parser transitions run within the pad read lock. */
static PadScriptReceipt receipt;
static uint64_t last_command_generation, observed_command_generation;

uint64_t pad_script_observed_command(void) {
    return observed_command_generation;
}

PadScriptReceipt pad_script_receipt(void) {
    PadScriptReceipt current = receipt;
    current.replay_state = replay_state;
    return current;
}

/* An ignored legacy token identifies a diagnostic publication without changing pad inputs.
 * Require a complete canonical body from the same stream and genuine parse semantics. */
static void receipt_parse(FILE *file, const char *nonce, const char *tag, unsigned words, int saw_finish) {
    char body[80], prefix[48];
    int read_ok = !ferror(file);
#ifdef _WIN32
    /* Inspect the same open publication without text CTRL-Z translation. */
    if (read_ok) read_ok = _setmode(_fileno(file), _O_BINARY) != -1;
#endif
    read_ok = read_ok && fseek(file, 0, SEEK_SET) == 0;
    const size_t size = read_ok ? fread(body, 1, sizeof(body), file) : 0;
    const int complete = read_ok && !ferror(file) && feof(file);
    ++receipt.native_generation;
    receipt.command_generation = observed_command_generation = 0;
    receipt.buttons = injected.buttons;
    memcpy(receipt.axes, injected.stick, sizeof(receipt.axes));
    receipt.touch_side = injected.touch_side;
    receipt.healthy_file = complete;
    receipt.kind = PAD_RECEIPT_FOREIGN;
    if (!complete) return;
    if (!size && !words) {
        receipt.kind = PAD_RECEIPT_EMPTY;
        return;
    }
    if (injected.buttons || injected.touch_side != -1 || injected.stick[0] != -1 ||
        injected.stick[1] != -1 || injected.stick[3] != -1) return;

    const int rx = injected.stick[2];
    const int len = rx == -1 ? snprintf(prefix, sizeof(prefix), "receipt=%s/", nonce)
                             : snprintf(prefix, sizeof(prefix), "rx=%d receipt=%s/", rx, nonce);
    if (len < 0 || (size_t)len >= sizeof(prefix) || (saw_finish && rx != -1)) return;
    const size_t tag_end = (size_t)len + 16;
    if (size != tag_end + (saw_finish ? 7 : 0) || memcmp(body, prefix, (size_t)len) ||
        words != (rx == -1 && !saw_finish ? 1u : 2u) ||
        (saw_finish && memcmp(body + tag_end, " finish", 7))) return;
    const size_t tag_start = rx == -1 ? 0 : (size_t)len - (8 + 16 + 1);
    if (strlen(tag) != tag_end - tag_start ||
        memcmp(body + tag_start, tag, tag_end - tag_start)) return;
    uint64_t generation = 0;
    for (size_t i = (size_t)len; i < tag_end; ++i) {
        unsigned nibble;
        if (body[i] >= '0' && body[i] <= '9') nibble = (unsigned)(body[i] - '0');
        else if (body[i] >= 'a' && body[i] <= 'f') nibble = (unsigned)(body[i] - 'a' + 10);
        else return;
        generation = (generation << 4) | nibble;
    }
    observed_command_generation = generation;
    if (generation > last_command_generation) {
        last_command_generation = generation;
        receipt.command_generation = generation;
        if (saw_finish) receipt.kind = PAD_RECEIPT_FINISH;
        else receipt.kind = rx == -1 ? PAD_RECEIPT_CLEAR : PAD_RECEIPT_RX;
    }
}
static uint64_t replay_started;
static PadSample *replay;
static size_t replay_count, replay_next;

static FILE *recording;
static uint64_t recording_started;
static PadSample last_recorded;

static const char *env_once(const char *name, const char **cache, int *read) {
    if (!*read) {
        *cache = getenv(name);
        *read = 1;
    }
    return *cache;
}

static void read_pad_file(void) {
    static const char *path;
    static int path_read;
    static uint64_t last_look;
    static long long seen_time, seen_stamp;
    env_once("BB_PAD_FILE", &path, &path_read);
    if (!path || !*path) return;
    const char *nonce = pad_guest_receipt_nonce();
    uint64_t now = pad_now_us();
    if (now - last_look < 20000) return;
    last_look = now;
    struct stat info;
    if (stat(path, &info)) {
        if (nonce) receipt.healthy_file = 0;
        return;
    }
#ifdef _WIN32
    long long stamp = (long long)info.st_size;
#else
    long long stamp = (long long)info.st_mtim.tv_nsec;
#endif
    if ((long long)info.st_mtime == seen_time && stamp == seen_stamp) return;
    seen_time = (long long)info.st_mtime;
    seen_stamp = stamp;
    FILE *file = fopen(path, "r");
    if (!file) {
        if (nonce) receipt.healthy_file = 0;
        return;
    }
    static const struct { const char *name; uint32_t button; } words[] = {
        {"cross", PAD_CROSS}, {"circle", PAD_CIRCLE}, {"square", PAD_SQUARE}, {"triangle", PAD_TRIANGLE},
        {"l1", PAD_L1}, {"r1", PAD_R1}, {"l2", PAD_L2}, {"r2", PAD_R2}, {"l3", PAD_L3}, {"r3", PAD_R3},
        {"options", PAD_OPTIONS}, {"touchpad", PAD_TOUCHPAD},
        {"up", PAD_UP}, {"down", PAD_DOWN}, {"left", PAD_LEFT}, {"right", PAD_RIGHT},
    };
    static const char stick_words[4][4] = {"lx=", "ly=", "rx=", "ry="};
    injected.buttons = 0;
    injected.touch_side = -1;
    for (int i = 0; i < 4; ++i) injected.stick[i] = -1;
    char word[64], tag[64] = "";
    unsigned words_seen = 0;
    int saw_finish = 0;
    while (fscanf(file, "%63s", word) == 1) {
        if (nonce) {
            if (words_seen < 3) ++words_seen;
            if (!strncmp(word, "receipt=", 8)) memcpy(tag, word, strlen(word) + 1);
            if (!strcmp(word, "finish")) saw_finish = 1;
        }
        if (!strcmp(word, "replay") && replay_state != REPLAY_RUNNING) {
            replay_state = REPLAY_RUNNING;
            replay_started = 0;
        }
        if (!strcmp(word, "touchpad_left") || !strcmp(word, "touchpad_right")) {
            injected.buttons |= PAD_TOUCHPAD;
            injected.touch_side = !strcmp(word, "touchpad_right");
        }
        for (size_t i = 0; i < sizeof(words) / sizeof(*words); ++i)
            if (!strcmp(word, words[i].name)) injected.buttons |= words[i].button;
        for (int i = 0; i < 4; ++i)
            if (!strncmp(word, stick_words[i], 3)) {
                int value = atoi(word + 3);
                injected.stick[i] = value < 0 ? 0 : value > 255 ? 255 : value;
            }
    }
    if (nonce) receipt_parse(file, nonce, tag, words_seen, saw_finish);
    fclose(file);
    printf("Runtime: pad file: buttons 0x%x sticks %d %d %d %d\n", injected.buttons, injected.stick[0],
           injected.stick[1], injected.stick[2], injected.stick[3]);
}

void pad_script_record(const PadData *pad) {
    static const char *path;
    static int path_read, f9_held;
    env_once("BB_PAD_RECORD", &path, &path_read);
    if (!path || !*path || !pad_host_sdl_state()) return;
    const bool *keys = SDL_GetKeyboardState(NULL);
    int f9 = keys && keys[SDL_SCANCODE_F9];
    if (f9 && !f9_held) {
        if (recording) {
            fclose(recording);
            recording = NULL;
            printf("Runtime: pad recording stopped (%s)\n", path);
        } else if ((recording = fopen(path, "w"))) {
            recording_started = pad_now_us();
            memset(&last_recorded, 0xFF, sizeof(last_recorded));
            printf("Runtime: pad recording started (%s, F9 stops)\n", path);
        }
    }
    f9_held = f9;
    if (!recording) return;
    PadSample s = {(uint32_t)((pad_now_us() - recording_started) / 1000), pad->buttons,
                   {pad->left_x, pad->left_y, pad->right_x, pad->right_y}, pad->l2, pad->r2};
    if (s.buttons == last_recorded.buttons && !memcmp(s.axes, last_recorded.axes, 4) && s.l2 == last_recorded.l2 &&
        s.r2 == last_recorded.r2)
        return;
    last_recorded = s;
    fprintf(recording, "%u %u %u %u %u %u %u %u\n", s.ms, s.buttons, s.axes[0], s.axes[1], s.axes[2], s.axes[3],
            s.l2, s.r2);
    fflush(recording);
}

static void load_replay(void) {
    const char *path = getenv("BB_PAD_REPLAY");
    FILE *file = path ? fopen(path, "r") : NULL;
    size_t capacity = 0;
    unsigned v[8];
    while (file && fscanf(file, "%u %u %u %u %u %u %u %u", &v[0], &v[1], &v[2], &v[3], &v[4], &v[5], &v[6], &v[7]) == 8) {
        if (replay_count == capacity) {
            capacity = capacity ? capacity * 2 : 1024;
            PadSample *grown = realloc(replay, capacity * sizeof(*replay));
            if (!grown) break;
            replay = grown;
        }
        replay[replay_count++] = (PadSample){v[0], v[1], {(uint8_t)v[2], (uint8_t)v[3], (uint8_t)v[4], (uint8_t)v[5]},
                                             (uint8_t)v[6], (uint8_t)v[7]};
    }
    if (file) fclose(file);
    printf("Runtime: pad replay of %zu samples from %s\n", replay_count, path ? path : "(unset)");
}

static void play_replay(PadData *pad) {
    if (replay_state == REPLAY_OFF) return;
    if (!replay_started) {
        static int loaded;
        if (!loaded) {
            loaded = 1;
            load_replay();
        }
        replay_started = pad_now_us();
        replay_next = 0;
    }
    uint32_t ms = (uint32_t)((pad_now_us() - replay_started) / 1000);
    while (replay_next < replay_count && replay[replay_next].ms <= ms) ++replay_next;
    if (!replay_next) return;
    if (replay_next == replay_count && ms > replay[replay_count - 1].ms + 500) {
        if (replay_state == REPLAY_RUNNING) {
            puts("Runtime: pad replay finished");
            replay_state = REPLAY_DONE;
        }
        return;
    }
    const PadSample *s = &replay[replay_next - 1];
    pad->buttons = s->buttons;
    pad->left_x = s->axes[0];
    pad->left_y = s->axes[1];
    pad->right_x = s->axes[2];
    pad->right_y = s->axes[3];
    pad->l2 = s->l2;
    pad->r2 = s->r2;
}

void pad_script_buttons(PadData *pad) {
    read_pad_file();
    play_replay(pad);
    pad->buttons |= injected.buttons;
}

void pad_script_overrides(PadData *pad) {
    if (injected.touch_side >= 0) pad_touch_click(pad, injected.touch_side);
    else if ((pad->buttons & PAD_TOUCHPAD) && !pad->touch_count) pad_touch_click(pad, 0);
    if (injected.buttons & PAD_L2) pad->l2 = 255;
    if (injected.buttons & PAD_R2) pad->r2 = 255;
    uint8_t *axes[4] = {&pad->left_x, &pad->left_y, &pad->right_x, &pad->right_y};
    for (int i = 0; i < 4; ++i)
        if (injected.stick[i] >= 0) *axes[i] = (uint8_t)injected.stick[i];
}
