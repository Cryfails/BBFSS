// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <algorithm>
#include <array>
#include <charconv>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string_view>
#include <thread>
#include "bbport_live_knobs.h"
#include "common/types.h"
#include "video_core/renderer_vulkan/vk_common.h"

namespace Vulkan::BottleMotion {
constexpr u32 MaxOn = 8, MaxOff = 16;
constexpr u16 Pilot = 0xa357;
constexpr s32 TileX = 32, TileY = 32, Cell = 8;
constexpr std::array<float,3> Receiver{1.04286122f, .60899862f, .52314130f};
constexpr std::array<float,3> Opaque{-1.12754460f, .52398941f, 2.42806714f};

inline auto P(u64 v) { return static_cast<unsigned long long>(v); }

template <typename T>
bool Number(std::string_view text, T& out) {
    if (text.empty()) return false;
    const auto* end = text.data() + text.size();
    auto [ptr, ec] = std::from_chars(text.data(), end, out);
    return ec == std::errc{} && ptr == end;
}

inline u16 Run() {
    static const u16 run = [] {
        const char* raw = std::getenv("BB_BOTTLE_MOTION_T198");
        u16 key{};
        return raw && Number(raw,key) ? key : 0;
    }();
    return run;
}

struct Mark {
    u16 run{}, id{};
    u32 arm{};
    u8 on{};
    u64 scene{}, scene_ns{}, draw_tick{}, draw_ns{}, write{};
    VAddr address{};
    vk::Image image{};
    vk::Semaphore timeline{};
    std::thread::id writer{};
    explicit operator bool() const { return run && id && scene; }
};

inline bool Same(const Mark& a,const Mark& b) {
    return a && b && a.run==b.run && a.id==b.id && a.scene==b.scene &&
           a.write==b.write && a.address==b.address && a.image==b.image &&
           a.timeline==b.timeline && a.draw_tick==b.draw_tick && a.draw_ns==b.draw_ns &&
           a.arm==b.arm && a.on==b.on && a.writer==b.writer;
}

struct State {
    Mark mark{};
    u32 last_arm{}, remaining{}, next_id{}, on_count{}, off_count{};
    u32 arm_generation{~0u};
    bool desired_on{};
    bool bad{}, bottle{}, dlss{}, vendor_ok{}, tone{}, ui{};
    u64 scene_generation{}, bottle_tick{}, generation{}, color_uid{}, depth_uid{}, hdr_uid{}, hdr_write{}, ldr_uid{}, ldr_write{};
    u32 color_id{}, depth_id{}, ldr_id{}, ordinal{};
    vk::Image color{}, depth{}, hdr{}, ui_image{};
    vk::ImageView color_view{}, depth_view{};
    std::array<float,12> view{};
    std::array<float,4> proj{};
    std::array<float,2> jitter{};
    std::array<float,2> last_receiver{};
    bool have_receiver{};
};

inline State& Scene() {
    static thread_local State state;
    return state;
}

inline void ClearScene(State& s) {
    s.mark={};
    s.bad=s.bottle=s.dlss=s.vendor_ok=s.tone=s.ui=false;
    s.bottle_tick=s.generation=s.color_uid=s.depth_uid=s.hdr_uid=s.hdr_write=s.ldr_uid=s.ldr_write=0;
    s.color_id=s.depth_id=s.ldr_id=s.ordinal=0;
    s.color=s.depth=s.hdr=s.ui_image=vk::Image{};
    s.color_view=s.depth_view=vk::ImageView{};
}

inline bool Arm(std::string_view text, u32& serial, bool& on, u32& count) {
    const auto first=text.find('/');
    const auto second=first==text.npos?text.npos:text.find('/',first+1);
    if (second==text.npos || !Number(text.substr(0,first),serial) ||
        !Number(text.substr(second+1),count) || serial==0 || count==0 || count>2) {
        return false;
    }
    const auto arm=text.substr(first+1,second-first-1);
    on=arm=="1";
    return on || arm=="0";
}

inline void Begin(bool on, vk::Semaphore timeline, u64 qpc_ns) {
    auto& s=Scene();
    ClearScene(s);
    ++s.scene_generation;
    const auto live=BbLiveKnobs::Generation();
    if (live!=s.arm_generation) {
        s.arm_generation=live;
        const auto value=BbLiveKnobs::Lookup("BB_BOTTLE_MOTION_ARM");
        const char* raw=value.in_file?value.Get():nullptr;
        u32 serial=0, count=0; bool wanted=false;
        // A missing arm pauses selection. Unrelated live file updates do not refill a used arm.
        if (!raw || !*raw || !Arm(raw,serial,wanted,count)) s.remaining=0;
        else if (serial>s.last_arm) {
            s.last_arm=serial;
            s.desired_on=wanted;
            s.remaining=count;
        }
    }
    if (!s.remaining || s.desired_on!=on || !timeline || !qpc_ns ||
        (on?s.on_count>=MaxOn:s.off_count>=MaxOff)) return;
    --s.remaining;
    const auto lock=BbLiveKnobs::Lookup("BB_TEST_EXPOSURE_LOCK");
    if (!lock.Get() || std::strcmp(lock.Get(),"1")) return;
    if (on) ++s.on_count; else ++s.off_count;
    s.mark={.run=Run(),.id=u16(++s.next_id),.arm=s.last_arm,.on=u8(on),
            .scene=s.scene_generation,.scene_ns=qpc_ns,.timeline=timeline,.writer=std::this_thread::get_id()};
}

inline bool MarkerClear(const State& s) {
    for (const auto& p : {Receiver,Opaque}) {
        const auto lane=[&](u32 i) {
            return s.view[4*i]*p[0]+s.view[4*i+1]*p[1]+s.view[4*i+2]*p[2]+s.view[4*i+3];
        };
        const float z=lane(2);
        if (!std::isfinite(z) || !(z>.1f)) return false;
        const float x=(lane(0)*s.proj[0]/z*.5f+.5f)*3840.f;
        const float y=(lane(1)*s.proj[1]/z*.5f+.5f)*2160.f;
        constexpr float Margin=56.f;
        if (!(x>=Margin && y>=Margin && x<3840.f-Margin && y<2160.f-Margin) ||
            (x-Margin<TileX+8*Cell && x+Margin>=TileX &&
             y-Margin<TileY+8*Cell && y+Margin>=TileY)) return false;
    }
    return true;
}

inline void Refuse(State& s,const char* reason) {
    if (!s.mark || s.bad) return;
    s.bad=true;
    std::printf("[bottle-motion-t198] event=refused run=%u id=%u scene=%llu why=%s\n",
                u32(s.mark.run),u32(s.mark.id),P(s.mark.scene),reason);
}

constexpr u16 Crc(u16 run,u16 id) {
    u16 crc=0xffff;
    for (u8 byte : {u8(run>>8),u8(run),u8(id>>8),u8(id)}) {
        crc ^= u16(byte)<<8;
        for (int i=0;i<8;++i) crc=u16((crc<<1) ^ (crc&0x8000?0x1021:0));
    }
    return crc;
}

constexpr u64 Tile(u16 run,u16 id) {
    return u64(Pilot)<<48 | u64(run)<<32 | u64(id)<<16 | Crc(run,id);
}
} // namespace Vulkan::BottleMotion

