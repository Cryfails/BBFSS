// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r84_live-test-knobs): TOOL (branch dev/test-tools; never a feature branch or a pull
// request). The live knobs file: BB_LIVE_KNOBS_FILE names a text file of lines NAME=VALUE that a
// test runner may rewrite while the game runs. The toggle watcher (memory.c, toggle_watch) calls
// live_knobs_poll every 250 ms; a change is taken when two reads in a row give the same bytes, so
// a file caught half written is never taken (the slot worker also writes a temporary file and
// renames it over the file). A knob's reader asks BbLiveKnobs (gpu/shim/bbport_live_knobs.h)
// instead of std::getenv: the file's value when the file names the knob, else the environment's.
// Not set: no file is read, the generation stays 0, every reader gets the environment's value.
//
// A line: spaces and tabs around the name and the value (and a CR before the line end) are
// dropped; an empty line or one whose first other character is # is skipped. NAME is A-Z, 0-9 and
// _, not a digit first, at most 63 characters; VALUE at most 127 bytes, no NUL byte; a name given
// twice takes the later value (in the place of the first); at most 32 knobs. A UTF-8 byte order
// mark at the start is skipped. Any other line is not taken (counted; the first one's number is
// logged). A file of more than 4096 bytes is not taken at all (one line says so).
#ifndef BB_LIVE_KNOBS_H
#define BB_LIVE_KNOBS_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

enum {
    LIVE_KNOBS_MOST = 32,       // knobs in one file
    LIVE_KNOB_NAME_MAX = 64,    // a name's bytes with its NUL
    LIVE_KNOB_VALUE_MAX = 128,  // a value's bytes with its NUL
    LIVE_KNOBS_FILE_MOST = 4096 // the file's bytes
};

typedef struct {
    char name[LIVE_KNOB_NAME_MAX];
    char value[LIVE_KNOB_VALUE_MAX];
} LiveKnob;

typedef struct {
    LiveKnob knobs[LIVE_KNOBS_MOST]; // in the order of their first line
    int count;
    int bad;       // lines not taken
    int first_bad; // the first of them (1: the file's first line); 0: none
} LiveKnobTable;

// The table `size` bytes of `text` give (no NUL needed at the end). Pure.
void live_knobs_parse(const char *text, size_t size, LiveKnobTable *out);
// The knob's value in `table`, or NULL when it does not name it. Pure.
const char *live_knobs_find(const LiveKnobTable *table, const char *name);
typedef void (*LiveKnobSay)(void *context, const char *line);
// The change from `before` to `after` as log lines, one per knob: "Live knobs: NAME=VALUE" for a
// knob new or changed (in `after`'s order), then "Live knobs: NAME no longer in the file (the
// environment's value again)" for one gone. Returns how many; `say` may be NULL. Pure.
int live_knobs_describe(const LiveKnobTable *before, const LiveKnobTable *after, LiveKnobSay say,
                        void *context);

// + 1 at every change of the table runtime_live_knob answers from (read it with an acquire load).
extern uint32_t runtime_live_knobs_generation;
// 1 and the value (cut to `size` - 1 bytes) when the file named `name` at its last change, else 0.
int runtime_live_knob(const char *name, char *value, size_t size);
// One round of the watcher (one thread only): reads the file at `path`; a missing file holds no
// knobs; a file that cannot be opened or read now (its writer replacing it) is read next round.
void live_knobs_poll(const char *path);

#ifdef __cplusplus
}
#endif
#endif
