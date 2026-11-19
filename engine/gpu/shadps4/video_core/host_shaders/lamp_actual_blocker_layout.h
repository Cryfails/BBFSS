// SPDX-License-Identifier: GPL-3.0-or-later
#ifndef LAMP_ACTUAL_BLOCKER_LAYOUT_H
#define LAMP_ACTUAL_BLOCKER_LAYOUT_H
#define LAB_BASE (256u * 1024u)
#define LAB_HEADER 16u
#define LAB_TRACE 32u
#define LAB_OUTPUT 32u
#define LAB_VOTE 32u
#define LAB_VOTES 8u
#define LAB_PIXEL (LAB_TRACE + LAB_OUTPUT + LAB_VOTE * LAB_VOTES)
#define LAB_WORDS (LAB_HEADER + 2u * LAB_PIXEL)
#endif
