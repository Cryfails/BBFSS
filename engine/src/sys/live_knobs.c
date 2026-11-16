// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r84_live-test-knobs): TOOL (branch dev/test-tools; never a feature branch or a pull
// request). The live knobs file; its rules are in live_knobs.h.
#include "live_knobs.h"
#include "host_sync.h"
#include <errno.h>
#include <stdio.h>
#include <string.h>

uint32_t runtime_live_knobs_generation;
static HostMutex live_lock = HOST_MUTEX_INIT;
static LiveKnobTable live_table; // under live_lock: what runtime_live_knob answers from

static int live_blank(char c) {
    return c == ' ' || c == '\t' || c == '\r';
}

static int live_name_char(char c, int first) {
    return (c >= 'A' && c <= 'Z') || c == '_' || (!first && c >= '0' && c <= '9');
}

const char *live_knobs_find(const LiveKnobTable *table, const char *name) {
    for (int i = 0; i < table->count; ++i) {
        if (!strcmp(table->knobs[i].name, name)) return table->knobs[i].value;
    }
    return NULL;
}

// One line, [first, last) of `text` without blanks at either end: 1 when it is taken into `out`.
static int live_take(const char *text, size_t first, size_t last, LiveKnobTable *out) {
    size_t eq = first;
    while (eq < last && text[eq] != '=') ++eq;
    if (eq == last) return 0;
    size_t name_end = eq;
    while (name_end > first && live_blank(text[name_end - 1])) --name_end;
    size_t value_at = eq + 1;
    while (value_at < last && live_blank(text[value_at])) ++value_at;
    const size_t name_size = name_end - first, value_size = last - value_at;
    if (name_size == 0 || name_size >= (size_t)LIVE_KNOB_NAME_MAX ||
        value_size >= (size_t)LIVE_KNOB_VALUE_MAX) {
        return 0;
    }
    for (size_t i = 0; i < name_size; ++i) {
        if (!live_name_char(text[first + i], i == 0)) return 0;
    }
    if (value_size && memchr(text + value_at, '\0', value_size)) return 0;
    char name[LIVE_KNOB_NAME_MAX];
    memcpy(name, text + first, name_size);
    name[name_size] = '\0';
    LiveKnob *knob = NULL;
    for (int i = 0; i < out->count && !knob; ++i) {
        if (!strcmp(out->knobs[i].name, name)) knob = &out->knobs[i];
    }
    if (!knob) {
        if (out->count == LIVE_KNOBS_MOST) return 0;
        knob = &out->knobs[out->count++];
        memcpy(knob->name, name, name_size + 1);
    }
    memcpy(knob->value, text + value_at, value_size);
    knob->value[value_size] = '\0';
    return 1;
}

void live_knobs_parse(const char *text, size_t size, LiveKnobTable *out) {
    memset(out, 0, sizeof(*out));
    size_t at = 0;
    if (size >= 3 && (unsigned char)text[0] == 0xEF && (unsigned char)text[1] == 0xBB &&
        (unsigned char)text[2] == 0xBF) {
        at = 3;
    }
    for (int line = 1; at < size; ++line) {
        size_t end = at;
        while (end < size && text[end] != '\n') ++end;
        size_t first = at, last = end;
        while (first < last && live_blank(text[first])) ++first;
        while (last > first && live_blank(text[last - 1])) --last;
        at = end + 1;
        if (first == last || text[first] == '#') continue;
        if (!live_take(text, first, last, out)) {
            if (!out->bad) out->first_bad = line;
            ++out->bad;
        }
    }
}

int live_knobs_describe(const LiveKnobTable *before, const LiveKnobTable *after, LiveKnobSay say,
                        void *context) {
    char line[LIVE_KNOB_NAME_MAX + LIVE_KNOB_VALUE_MAX + 96];
    int changes = 0;
    for (int i = 0; i < after->count; ++i) {
        const char *was = live_knobs_find(before, after->knobs[i].name);
        if (was && !strcmp(was, after->knobs[i].value)) continue;
        snprintf(line, sizeof(line), "Live knobs: %s=%s", after->knobs[i].name, after->knobs[i].value);
        if (say) say(context, line);
        ++changes;
    }
    for (int i = 0; i < before->count; ++i) {
        if (live_knobs_find(after, before->knobs[i].name)) continue;
        snprintf(line, sizeof(line), "Live knobs: %s no longer in the file (the environment's value again)",
                 before->knobs[i].name);
        if (say) say(context, line);
        ++changes;
    }
    return changes;
}

int runtime_live_knob(const char *name, char *value, size_t size) {
    if (!name || !value || size == 0) return 0;
    host_lock(&live_lock);
    const char *found = live_knobs_find(&live_table, name);
    if (found) snprintf(value, size, "%s", found);
    host_unlock(&live_lock);
    return found != NULL;
}

// The watcher's own (one thread): the bytes of this read, of the read before it and of the table
// in force, and the two tables a change compares (static for their size).
static char live_read[LIVE_KNOBS_FILE_MOST + 1], live_last[LIVE_KNOBS_FILE_MOST],
    live_applied[LIVE_KNOBS_FILE_MOST];
static size_t live_last_size, live_applied_size;
static int live_last_ok, live_started, live_long_said;
static LiveKnobTable live_next, live_before;

static void live_print(void *context, const char *line) {
    (void)context;
    printf("%s\n", line);
}

void live_knobs_poll(const char *path) {
    if (!live_started) {
        live_started = 1;
        printf("Live knobs: the file BB_LIVE_KNOBS_FILE names is read every 250 ms; a change is "
               "taken when two reads in a row agree\n");
        fflush(stdout);
    }
    size_t size = 0;
    FILE *file = fopen(path, "rb");
    if (file) {
        size = fread(live_read, 1, sizeof(live_read), file);
        const int failed = ferror(file);
        fclose(file);
        if (failed) return; // the next round
        if (size > (size_t)LIVE_KNOBS_FILE_MOST) {
            if (!live_long_said) {
                live_long_said = 1;
                printf("Live knobs: the file holds more than %d bytes; not taken\n", LIVE_KNOBS_FILE_MOST);
                fflush(stdout);
            }
            live_last_ok = 0;
            return;
        }
        live_long_said = 0;
    } else if (errno != ENOENT) {
        return; // there but not open now (its writer replacing it): the next round
    }
    // A missing file: no knobs (size 0).
    if (size == live_applied_size && !memcmp(live_read, live_applied, size)) {
        live_last_ok = 0;
        return;
    }
    if (!live_last_ok || size != live_last_size || memcmp(live_read, live_last, size)) {
        memcpy(live_last, live_read, size);
        live_last_size = size;
        live_last_ok = 1;
        return; // taken when the next read agrees
    }
    live_last_ok = 0;
    memcpy(live_applied, live_read, size);
    live_applied_size = size;
    live_knobs_parse(live_read, size, &live_next);
    host_lock(&live_lock);
    live_before = live_table;
    live_table = live_next;
    host_unlock(&live_lock);
    if (live_knobs_describe(&live_before, &live_next, live_print, NULL)) {
        (void)__atomic_add_fetch(&runtime_live_knobs_generation, 1, __ATOMIC_RELEASE);
    }
    if (live_next.bad) {
        printf("Live knobs: %d line%s of the file not taken (the first: line %d); a line is NAME=VALUE, "
               "NAME of A-Z, 0-9 and _ (not a digit first) of at most %d characters, a value of at "
               "most %d bytes, at most %d knobs\n",
               live_next.bad, live_next.bad == 1 ? "" : "s", live_next.first_bad,
               LIVE_KNOB_NAME_MAX - 1, LIVE_KNOB_VALUE_MAX - 1, LIVE_KNOBS_MOST);
    }
    fflush(stdout);
}
