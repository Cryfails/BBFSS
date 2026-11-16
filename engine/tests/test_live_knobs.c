// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r84_live-test-knobs): TOOL (branch dev/test-tools). The live knobs file
// (src/sys/live_knobs.c): its line rule, the log lines of a change, and the watcher's rule that a
// change is taken when two reads in a row agree (live_knobs_poll on a file in the temporary
// folder, called here directly; in the game the toggle watcher calls it every 250 ms).
#include "sys/live_knobs.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static int failures;
#define EXPECT(condition) do { if (!(condition)) { printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #condition); ++failures; } } while (0)

static LiveKnobTable table, other; // static: 6 KB each

static void parse(const char *text) {
    live_knobs_parse(text, strlen(text), &table);
}

static int is(const LiveKnobTable *t, const char *name, const char *value) {
    const char *found = live_knobs_find(t, name);
    return found && !strcmp(found, value);
}

static char said[8][256];
static int said_count;

static void collect(void *context, const char *line) {
    (void)context;
    if (said_count < 8) snprintf(said[said_count], sizeof(said[0]), "%s", line);
    ++said_count;
}

static void lines(void) {
    parse("BB_A=1\nBB_B=2\n");
    EXPECT(table.count == 2 && is(&table, "BB_A", "1") && is(&table, "BB_B", "2") && table.bad == 0 &&
           table.first_bad == 0);
    EXPECT(!strcmp(table.knobs[0].name, "BB_A") && !strcmp(table.knobs[1].name, "BB_B"));
    EXPECT(live_knobs_find(&table, "BB_C") == NULL && live_knobs_find(&table, "BB_") == NULL);
    // CRLF, blanks around the name and the value, comments, empty lines, an empty value, a byte
    // order mark at the start
    parse("\xEF\xBB\xBF# a comment\r\n  BB_A = 1 \r\n\r\n\t# BB_B=2\r\nBB_C=\r\n   \r\n");
    EXPECT(table.count == 2 && is(&table, "BB_A", "1") && is(&table, "BB_C", "") && table.bad == 0);
    // The last line without its line end is taken
    parse("BB_A=1\nBB_B=2");
    EXPECT(table.count == 2 && is(&table, "BB_B", "2"));
    // A value keeps '=', '#' and its inner blanks
    parse("BB_A=a=b # c\n");
    EXPECT(table.count == 1 && is(&table, "BB_A", "a=b # c"));
    // Not taken: lower case, no '=', no name, a digit first, a '-', a blank inside the name
    parse("lower=1\nBB_A\n=1\n1BB=2\nBB-A=3\nBB A=4\nBB_OK=5\n");
    EXPECT(table.count == 1 && is(&table, "BB_OK", "5") && table.bad == 6 && table.first_bad == 1);
    parse("BB_OK=1\n\nnot a knob\n");
    EXPECT(table.count == 1 && table.bad == 1 && table.first_bad == 3);
    // A name given twice: the later value, in the place of the first
    parse("BB_A=1\nBB_B=2\nBB_A=3\n");
    EXPECT(table.count == 2 && is(&table, "BB_A", "3") && !strcmp(table.knobs[0].name, "BB_A"));
    // A NUL byte inside a value: not taken
    live_knobs_parse("BB_A=1\0x\nBB_B=2\n", 16, &table);
    EXPECT(table.count == 1 && is(&table, "BB_B", "2") && table.bad == 1 && table.first_bad == 1);
    // The limits: a name of 63 characters and a value of 127 bytes; one more is not taken
    {
        char text[600], name[80], value[160];
        memset(name, 'N', 63);
        name[63] = '\0';
        memset(value, 'v', 127);
        value[127] = '\0';
        snprintf(text, sizeof(text), "%s=%s\n", name, value);
        parse(text);
        EXPECT(table.count == 1 && is(&table, name, value));
        snprintf(text, sizeof(text), "%sN=1\nBB_A=%sv\n", name, value);
        parse(text);
        EXPECT(table.count == 0 && table.bad == 2 && table.first_bad == 1);
    }
    // At most 32 knobs: a 33rd name is not taken; a later line naming one of the 32 is
    {
        char text[2048];
        size_t at = 0;
        for (int i = 0; i < 33; ++i) at += (size_t)snprintf(text + at, sizeof(text) - at, "BB_K%d=%d\n", i, i);
        at += (size_t)snprintf(text + at, sizeof(text) - at, "BB_K0=again\n");
        live_knobs_parse(text, at, &table);
        EXPECT(table.count == LIVE_KNOBS_MOST && table.bad == 1 && table.first_bad == 33 &&
               is(&table, "BB_K31", "31") && is(&table, "BB_K0", "again") && !live_knobs_find(&table, "BB_K32"));
    }
    // Nothing at all
    live_knobs_parse("", 0, &table);
    EXPECT(table.count == 0 && table.bad == 0);
}

static void changes(void) {
    parse("BB_A=1\nBB_B=2\n");
    other = table;
    parse("BB_A=1\nBB_B=3\nBB_C=\n");
    said_count = 0;
    EXPECT(live_knobs_describe(&other, &table, collect, NULL) == 2 && said_count == 2);
    EXPECT(!strcmp(said[0], "Live knobs: BB_B=3") && !strcmp(said[1], "Live knobs: BB_C="));
    other = table;
    parse("BB_C=\n");
    said_count = 0;
    EXPECT(live_knobs_describe(&other, &table, collect, NULL) == 2 && said_count == 2);
    EXPECT(!strcmp(said[0], "Live knobs: BB_A no longer in the file (the environment's value again)") &&
           !strcmp(said[1], "Live knobs: BB_B no longer in the file (the environment's value again)"));
    EXPECT(live_knobs_describe(&table, &table, collect, NULL) == 0 && said_count == 2);
    EXPECT(live_knobs_describe(&other, &table, NULL, NULL) == 2);
}

static int write_file(const char *path, const char *text, size_t size) {
    FILE *file = fopen(path, "wb");
    if (!file) return 0;
    const size_t wrote = fwrite(text, 1, size, file);
    const int closed = fclose(file) == 0;
    return closed && wrote == size;
}

static uint32_t generation(void) {
    return __atomic_load_n(&runtime_live_knobs_generation, __ATOMIC_ACQUIRE);
}

static void watcher(void) {
    char path[600], value[LIVE_KNOB_VALUE_MAX];
    const char *folder = getenv("TEMP");
    if (!folder || !folder[0]) folder = getenv("TMPDIR");
    if (!folder || !folder[0]) folder = ".";
    snprintf(path, sizeof(path), "%.500s/live-knobs-test-%u.tmp", folder, (unsigned)time(NULL));
    (void)remove(path);
    // No file: no knobs, nothing changes
    live_knobs_poll(path);
    live_knobs_poll(path);
    EXPECT(generation() == 0 && !runtime_live_knob("BB_A", value, sizeof(value)));
    // A new file is taken at the read that agrees with the one before it
    EXPECT(write_file(path, "BB_A=1\n", 7));
    live_knobs_poll(path);
    EXPECT(generation() == 0 && !runtime_live_knob("BB_A", value, sizeof(value)));
    live_knobs_poll(path);
    EXPECT(generation() == 1 && runtime_live_knob("BB_A", value, sizeof(value)) && !strcmp(value, "1"));
    live_knobs_poll(path);
    EXPECT(generation() == 1);
    // A file caught while it changes (two reads that differ) is not taken until two agree
    EXPECT(write_file(path, "BB_A=2\n", 7));
    live_knobs_poll(path);
    EXPECT(write_file(path, "BB_A=3\nBB_B=x\n", 14));
    live_knobs_poll(path);
    EXPECT(generation() == 1 && runtime_live_knob("BB_A", value, sizeof(value)) && !strcmp(value, "1"));
    live_knobs_poll(path);
    EXPECT(generation() == 2 && runtime_live_knob("BB_A", value, sizeof(value)) && !strcmp(value, "3"));
    // The value cut to the caller's buffer
    EXPECT(runtime_live_knob("BB_B", value, 1) && value[0] == '\0');
    // Only a comment changed: the same knobs, no new generation
    EXPECT(write_file(path, "# x\nBB_A=3\nBB_B=x\n", 18));
    live_knobs_poll(path);
    live_knobs_poll(path);
    EXPECT(generation() == 2);
    // A file of more than LIVE_KNOBS_FILE_MOST bytes is not taken
    {
        static char big[LIVE_KNOBS_FILE_MOST + 100];
        memset(big, '#', sizeof(big));
        EXPECT(write_file(path, big, sizeof(big)));
        live_knobs_poll(path);
        live_knobs_poll(path);
        EXPECT(generation() == 2 && runtime_live_knob("BB_A", value, sizeof(value)) && !strcmp(value, "3"));
    }
    // The file removed: no knobs (the environment's values again)
    EXPECT(remove(path) == 0);
    live_knobs_poll(path);
    live_knobs_poll(path);
    EXPECT(generation() == 3 && !runtime_live_knob("BB_A", value, sizeof(value)) &&
           !runtime_live_knob("BB_B", value, sizeof(value)));
    EXPECT(!runtime_live_knob(NULL, value, sizeof(value)) && !runtime_live_knob("BB_A", NULL, 4));
}

int main(void) {
    setvbuf(stdout, NULL, _IOLBF, 4096);
    lines();
    changes();
    watcher();
    if (failures) return 1;
    puts("live knobs: PASS");
    return 0;
}
