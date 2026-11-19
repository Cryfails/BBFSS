/* C interface of the GPU library (gpu/): shadPS4's Liverpool/Vulkan video core,
 * GnmDriver, VideoOut and kernel event queues, adapted to the native loader. */
#ifndef BBGPU_H
#define BBGPU_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
typedef struct {
    const char *title;          /* window title */
    const char *serial;         /* CUSA id, names the pipeline cache */
    const char *user_dir;       /* pipeline cache/logs directory */
    uint32_t sdk_version;       /* from the eboot's procparam */
    uint32_t psf_attributes;    /* param.sfo ATTRIBUTE */
    int32_t width, height;      /* initial window size */
} BbGpuConfig;
/* Registers kernel event queues (needed with or without graphics). */
void bbgpu_register_kernel(void);
/* Start networking after game metadata, guest TLS and linked modules are ready. */
void bbgpu_start_online(void);
/* Creates window, Vulkan device, presenter and GPU command processor. */
int bbgpu_init(const BbGpuConfig *config);
/* Function for an imported NID ("NID#lib#mod"), or 0 when the GPU library does not provide it. */
uintptr_t bbgpu_resolve(const char *scoped_nid);
/* Called first by the loader's SIGSEGV handler: 1 when a GPU page-tracking fault was handled.
 * The context is the handler's ucontext_t (Linux) or the vectored exception handler's
 * EXCEPTION_POINTERS (Windows). */
int bbgpu_handle_fault(void *ucontext, void *address);
/* BB_WRITE_LOG=1: prints the logged GPU-side writes to guest memory near the fault
 * (same context as bbgpu_handle_fault). */
void bbgpu_dump_guest_writes(void *ucontext);
/* Keyboard text entry through the game window (IME dialog). begin returns 0 when
 * no window exists; poll returns 0 typing, 1 confirmed, 2 cancelled (UTF-8 text). */
int bbgpu_text_input_begin(const char *initial_utf8, const char *prompt_utf8);
int bbgpu_text_input_poll(char *out_utf8, uint64_t size);
/* 1 while the in-game settings menu is open: the game's pad input is held neutral. */
int bbgpu_overlay_captures_input(void);
/* The overlay's L3 chords on the D-pad, as SDL gamepad button bits: bits 0-15 the D-pad buttons
 * whose down event the overlay has seen with no up event since, bits 16-31 those of them whose
 * down event fired a chord (BbOverlay::PadChords). */
uint32_t bbgpu_overlay_pad_chords(void);
int bbgpu_window_in_background(void);
void bbgpu_anti_lag_before_input(void);
/* Patches the loaded image before the game runs (image still writable): libGnm entry hooks. */
void bbgpu_patch_image(unsigned char *image, uint64_t size);
/* Number of symbols registered by the vendored libraries (diagnostics). */
unsigned bbgpu_symbol_count(void);
/* bbport (r108_spark-probe, TOOL): the pad buttons the game was just given (scePadReadState);
 * BB_SPARK_PROBE=1 takes the transform button's presses from them, otherwise it returns at once. */
void bbgpu_spark_probe_pad(uint32_t buttons);
/* bbport (r110_weapon-sparks): the pad buttons the game was just given (scePadReadState);
 * BB_WEAPON_SPARKS takes the transform button's presses from them, otherwise it returns at once. */
void bbgpu_weapon_sparks_pad(uint32_t buttons);
/* Private T05 diagnostic. The native pad owner serializes stops against successful returns. */
typedef struct {
    uint64_t request, loading, generation, command, scene;
    uint32_t frame;
} BbSewerPadKey;

typedef enum {
    BB_SEWER_PAD_FEEDBACK, BB_SEWER_PAD_ARM, BB_SEWER_PAD_STOP, BB_SEWER_PAD_CANCEL
} BbSewerPadAction;

typedef enum {
    BB_SEWER_PAD_WAITING, BB_SEWER_PAD_ARMED, BB_SEWER_PAD_CUT, BB_SEWER_PAD_REFUSED
} BbSewerPadPhase;

typedef enum {
    BB_SEWER_PAD_NONE, BB_SEWER_PAD_PROJECTION, BB_SEWER_PAD_CANCELLED,
    BB_SEWER_PAD_EARLY_RX, BB_SEWER_PAD_HOST_LEASE, BB_SEWER_PAD_RENDER_LEASE,
    BB_SEWER_PAD_ABSOLUTE, BB_SEWER_PAD_OWNER, BB_SEWER_PAD_INPUT,
    BB_SEWER_PAD_BUDGET, BB_SEWER_PAD_PUBLICATION
} BbSewerPadCause;

typedef struct {
    BbSewerPadPhase phase;
    BbSewerPadCause stop_cause, fault;
    uint64_t stop_serial, after_read, first_read;
    uint64_t stop_loading, stop_generation, stop_scene, heartbeat;
    uint32_t stop_frame, owner;
    int first_inherited;
} BbSewerPadStatus;

BbSewerPadStatus bbgpu_sewer_pad_latch(BbSewerPadAction action, const BbSewerPadKey *key);
#ifdef __cplusplus
}
#endif
#endif
