// SPDX-License-Identifier: GPL-3.0-or-later
#include "sys/sys.h"
#include "sys/pad.h"
#include "gpu/shim/input/input.h"
#include <SDL3/SDL.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int capture, menu, failures;
static uint32_t overlay_chords;
static bool keyboard[SDL_SCANCODE_COUNT];

#define CHECK(condition) do { if (!(condition)) { fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #condition); ++failures; } } while (0)

uint64_t host_monotonic_ns(void) {
    return SDL_GetTicksNS();
}
int bbgpu_overlay_captures_input(void) { return capture; }
uint32_t bbgpu_overlay_pad_chords(void) { return overlay_chords; }
void bbgpu_anti_lag_before_input(void) {}
int bbgpu_pc_input(BbPcPad *pad, const bool *keys, int count, int gamepad) {
    (void)pad;
    (void)keys;
    (void)count;
    (void)gamepad;
    return 0;
}
int bbgpu_menu_buttons(uint32_t *confirm, uint32_t *back) {
    *confirm = PAD_CROSS;
    *back = PAD_CIRCLE;
    return menu;
}
const bool *SDL_GetKeyboardState(int *count) {
    if (count) *count = SDL_SCANCODE_COUNT;
    return keyboard;
}

typedef int32_t (SYS_ABI *Init)(void);
typedef int32_t (SYS_ABI *Open)(int32_t, int32_t, int32_t, const void *);
typedef int32_t (SYS_ABI *Read)(int32_t, PadData *);

static void *find(const char *nid) {
    const SysExport *e = sys_find(nid, NULL);
    return e ? e->function : NULL;
}

static void write_file(const char *path, const char *text) {
    FILE *file = fopen(path, "w");
    CHECK(file != NULL);
    if (!file) return;
    fputs(text, file);
    fclose(file);
    SDL_Delay(25);
}

static void temp_path(char *out, size_t size, const char *name) {
    const char *dir = getenv("TMPDIR");
    if (!dir) dir = getenv("TEMP");
    if (!dir) dir = "/tmp";
    snprintf(out, size, "%s/lantern-%s-%u", dir, name, (unsigned)SDL_GetTicks());
}

static void set_env(const char *name, const char *value) {
#ifdef _WIN32
    _putenv_s(name, value);
#else
    setenv(name, value, 1);
#endif
}

static void update(void) {
    SDL_UpdateJoysticks();
    SDL_UpdateGamepads();
}

int main(void) {
    char pad_file[512], config[512];
    temp_path(pad_file, sizeof(pad_file), "pad-file");
    temp_path(config, sizeof(config), "pad-config");
    write_file(pad_file, "");
    write_file(config, "upscaler=fsr3\npad.cross=b\npad.circle=a\npad.r2=rightshoulder\n"
                       "pad.r1=righttrigger\nkey.cross=X, Space\npad.bogus=a\npad.menu_back=b\n");
    set_env("BB_PAD_FILE", pad_file);
    set_env("BB_CONFIG", config);
    set_env("SDL_VIDEODRIVER", "dummy");
    SDL_SetHint(SDL_HINT_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT, "0x1d50/0x6189");
    if (!SDL_Init(SDL_INIT_VIDEO | SDL_INIT_GAMEPAD)) {
        fprintf(stderr, "SDL_Init failed: %s\n", SDL_GetError());
        return 1;
    }
    Init init = find("hv1luiJrqQM");
    Open open = find("xk0AcarP3V4");
    Read read = find("YndgXqQVV7c");
    CHECK(init && open && read);
    if (failures) return 1;
    CHECK(init() == 0 && open(1, 0, 0, NULL) == 1);
    PadData data;

    write_file(pad_file, "cross l3 touchpad_left");
    CHECK(read(1, &data) == 0);
    CHECK((data.buttons & (PAD_CROSS | PAD_L3 | PAD_TOUCHPAD)) == (PAD_CROSS | PAD_L3 | PAD_TOUCHPAD));
    CHECK(data.touch_count == 1 && data.touches[0].x == 480 && data.touches[0].y == 471 && data.touches[0].id == 1);
    write_file(pad_file, "touchpad_right");
    CHECK(read(1, &data) == 0 && data.touch_count == 1 && data.touches[0].x == 1440);
    write_file(pad_file, "");
    CHECK(read(1, &data) == 0 && data.buttons == 0 && data.touch_count == 0);

    keyboard[SDL_SCANCODE_X] = true;
    CHECK(read(1, &data) == 0 && data.buttons == PAD_CROSS);
    keyboard[SDL_SCANCODE_X] = false;
    keyboard[SDL_SCANCODE_SPACE] = true;
    CHECK(read(1, &data) == 0 && data.buttons == PAD_CROSS);
    keyboard[SDL_SCANCODE_SPACE] = false;

    SDL_VirtualJoystickTouchpadDesc touch = {.nfingers = 2};
    SDL_VirtualJoystickDesc desc;
    SDL_INIT_INTERFACE(&desc);
    desc.type = SDL_JOYSTICK_TYPE_GAMEPAD;
    desc.naxes = SDL_GAMEPAD_AXIS_COUNT;
    desc.nbuttons = SDL_GAMEPAD_BUTTON_COUNT;
    desc.button_mask = (1u << SDL_GAMEPAD_BUTTON_COUNT) - 1;
    desc.axis_mask = (1u << SDL_GAMEPAD_AXIS_COUNT) - 1;
    desc.name = "lantern test controller";
    desc.vendor_id = 0x1d50;
    desc.product_id = 0x6189;
    desc.ntouchpads = 1;
    desc.touchpads = &touch;
    SDL_JoystickID id = SDL_AttachVirtualJoystick(&desc);
    CHECK(id != 0);
    SDL_Joystick *joystick = SDL_OpenJoystick(id);
    CHECK(joystick != NULL);
    if (failures) return 1;

    CHECK(SDL_SetJoystickVirtualTouchpad(joystick, 0, 0, true, 0.75f, 0.5f, 1.0f));
    CHECK(SDL_SetJoystickVirtualTouchpad(joystick, 0, 1, true, 0.25f, 1.0f, 1.0f));
    CHECK(SDL_SetJoystickVirtualButton(joystick, SDL_GAMEPAD_BUTTON_TOUCHPAD, true));
    update();
    CHECK(read(1, &data) == 0 && data.touch_count == 2 && (data.buttons & PAD_TOUCHPAD));
    CHECK(data.touches[0].x == 1439 && data.touches[0].y == 471 && data.touches[0].id == 2);
    CHECK(data.touches[1].x == 480 && data.touches[1].y == 942 && data.touches[1].id == 3);
    capture = 1;
    CHECK(read(1, &data) == 0 && data.touch_count == 0 && data.buttons == 0);
    capture = 0;
    CHECK(SDL_SetJoystickVirtualTouchpad(joystick, 0, 0, false, 0, 0, 0));
    CHECK(SDL_SetJoystickVirtualTouchpad(joystick, 0, 1, false, 0, 0, 0));
    update();
    CHECK(read(1, &data) == 0 && data.touch_count == 1 && data.touches[0].x == 480);
    CHECK(SDL_SetJoystickVirtualButton(joystick, SDL_GAMEPAD_BUTTON_TOUCHPAD, false));
    update();
    CHECK(read(1, &data) == 0 && data.buttons == 0);

    CHECK(SDL_SetJoystickVirtualButton(joystick, SDL_GAMEPAD_BUTTON_EAST, true));
    CHECK(SDL_SetJoystickVirtualButton(joystick, SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER, true));
    CHECK(SDL_SetJoystickVirtualAxis(joystick, SDL_GAMEPAD_AXIS_RIGHT_TRIGGER, 32767));
    update();
    CHECK(read(1, &data) == 0 && data.buttons == (PAD_CROSS | PAD_R2 | PAD_R1) && data.r2 == 255);
    menu = 1;
    CHECK(read(1, &data) == 0 && (data.buttons & (PAD_CROSS | PAD_CIRCLE)) == PAD_CIRCLE);
    menu = 0;
    CHECK(read(1, &data) == 0 && !(data.buttons & (PAD_CROSS | PAD_CIRCLE)));
    CHECK(sys_pad_button(PAD_CROSS, 0) == SDL_GAMEPAD_BUTTON_EAST);
    CHECK(SDL_SetJoystickVirtualButton(joystick, SDL_GAMEPAD_BUTTON_EAST, false));
    CHECK(SDL_SetJoystickVirtualButton(joystick, SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER, false));
    // A virtual trigger at rest is SDL_JOYSTICK_AXIS_MIN (SDL_SetJoystickVirtualAxis); 0 is half pressed.
    CHECK(SDL_SetJoystickVirtualAxis(joystick, SDL_GAMEPAD_AXIS_RIGHT_TRIGGER, SDL_JOYSTICK_AXIS_MIN));
    update();
    CHECK(read(1, &data) == 0 && data.buttons == 0);

    // L3 + a D-pad direction is an overlay chord: a D-pad button pressed while L3 is held is not
    // the game's until it is released; L3 is, and so is a D-pad button held before L3.
    CHECK(SDL_SetJoystickVirtualButton(joystick, SDL_GAMEPAD_BUTTON_DPAD_UP, true));
    update();
    CHECK(read(1, &data) == 0 && data.buttons == PAD_UP);
    CHECK(SDL_SetJoystickVirtualButton(joystick, SDL_GAMEPAD_BUTTON_LEFT_STICK, true));
    update();
    CHECK(read(1, &data) == 0 && data.buttons == (PAD_L3 | PAD_UP));
    CHECK(SDL_SetJoystickVirtualButton(joystick, SDL_GAMEPAD_BUTTON_DPAD_LEFT, true));
    CHECK(SDL_SetJoystickVirtualButton(joystick, SDL_GAMEPAD_BUTTON_DPAD_RIGHT, true));
    CHECK(SDL_SetJoystickVirtualButton(joystick, SDL_GAMEPAD_BUTTON_DPAD_DOWN, true));
    update();
    CHECK(read(1, &data) == 0 && data.buttons == (PAD_L3 | PAD_UP));
    CHECK(SDL_SetJoystickVirtualButton(joystick, SDL_GAMEPAD_BUTTON_LEFT_STICK, false));
    CHECK(SDL_SetJoystickVirtualButton(joystick, SDL_GAMEPAD_BUTTON_DPAD_UP, false));
    update();
    CHECK(read(1, &data) == 0 && data.buttons == 0); // L3 let go first: the chord's stay away
    CHECK(SDL_SetJoystickVirtualButton(joystick, SDL_GAMEPAD_BUTTON_DPAD_LEFT, false));
    CHECK(SDL_SetJoystickVirtualButton(joystick, SDL_GAMEPAD_BUTTON_DPAD_DOWN, false));
    update();
    CHECK(read(1, &data) == 0 && data.buttons == 0);
    CHECK(SDL_SetJoystickVirtualButton(joystick, SDL_GAMEPAD_BUTTON_DPAD_RIGHT, false));
    CHECK(SDL_SetJoystickVirtualButton(joystick, SDL_GAMEPAD_BUTTON_DPAD_LEFT, true));
    update();
    CHECK(read(1, &data) == 0 && data.buttons == PAD_LEFT); // pressed again without L3
    CHECK(SDL_SetJoystickVirtualButton(joystick, SDL_GAMEPAD_BUTTON_DPAD_LEFT, false));
    update();
    CHECK(read(1, &data) == 0 && data.buttons == 0);

    // Once the overlay has seen a press it decides (bbgpu_overlay_pad_chords): a press that fired
    // a chord stays away after L3 is let go; a press it saw fire none is the game's with L3 down
    // (D-pad Down with scout mode off, or D-pad pressed just before L3).
    const uint32_t left = 1u << SDL_GAMEPAD_BUTTON_DPAD_LEFT, down = 1u << SDL_GAMEPAD_BUTTON_DPAD_DOWN;
    CHECK(SDL_SetJoystickVirtualButton(joystick, SDL_GAMEPAD_BUTTON_LEFT_STICK, true));
    CHECK(SDL_SetJoystickVirtualButton(joystick, SDL_GAMEPAD_BUTTON_DPAD_LEFT, true));
    update();
    CHECK(read(1, &data) == 0 && data.buttons == PAD_L3); // not seen by the overlay yet
    overlay_chords = left | left << 16;                    // seen: it fired clean shot
    CHECK(SDL_SetJoystickVirtualButton(joystick, SDL_GAMEPAD_BUTTON_LEFT_STICK, false));
    update();
    CHECK(read(1, &data) == 0 && data.buttons == 0);
    CHECK(SDL_SetJoystickVirtualButton(joystick, SDL_GAMEPAD_BUTTON_LEFT_STICK, true));
    CHECK(SDL_SetJoystickVirtualButton(joystick, SDL_GAMEPAD_BUTTON_DPAD_DOWN, true));
    update();
    CHECK(read(1, &data) == 0 && data.buttons == PAD_L3); // new with L3 down, not seen yet
    overlay_chords |= down;                               // seen: no chord
    CHECK(read(1, &data) == 0 && data.buttons == (PAD_L3 | PAD_DOWN));
    CHECK(SDL_SetJoystickVirtualButton(joystick, SDL_GAMEPAD_BUTTON_LEFT_STICK, false));
    CHECK(SDL_SetJoystickVirtualButton(joystick, SDL_GAMEPAD_BUTTON_DPAD_LEFT, false));
    CHECK(SDL_SetJoystickVirtualButton(joystick, SDL_GAMEPAD_BUTTON_DPAD_DOWN, false));
    update();
    overlay_chords = 0;
    CHECK(read(1, &data) == 0 && data.buttons == 0);

    SDL_CloseJoystick(joystick);
    SDL_DetachVirtualJoystick(id);
    SDL_Quit();
    remove(pad_file);
    remove(config);
    if (failures) return 1;
    puts("PASS: pad ABI, left/right clicks, SDL touch coordinates, overlay capture, controls, menu buttons, L3 chords");
    return 0;
}
