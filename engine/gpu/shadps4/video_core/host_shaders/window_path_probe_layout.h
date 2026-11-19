// SPDX-License-Identifier: GPL-3.0-or-later
#ifndef WINDOW_PATH_PROBE_LAYOUT_H
#define WINDOW_PATH_PROBE_LAYOUT_H
#define WP_RECEIVERS 8u
#define WP_LAMPS 4u
#define WP_SEGMENTS 40u
#define WP_SELECTED 8u
#define WP_TRI_WORDS 8u
#define WP_RECORDS 8192u
#define WP_CANDIDATES 32u
#define WP_NONE 0xffffffffu
#define WP_COMPLETE 1u
#define WP_OVERFLOW 2u
#define WP_UNKNOWN 3u
#define WP_BAD_TYPE 4u
#define WP_BAD_INPUT 5u
#define WP_PANE 0u
#define WP_ACTUAL 1u
#define WP_SKIP 2u
#define WP_ACCEPT(mode, selected) ((mode) == WP_PANE ? (selected) : ((mode) == WP_ACTUAL || !(selected)))
#endif
