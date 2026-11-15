// SPDX-License-Identifier: GPL-2.0-or-later
// bbport: a reduced depth proxy written into a native-size R32F color image (the game's depth
// block copy, SceneTargets::CopyDepthProxyToColor). Nearest, with the texel mapping of
// depth_resample.frag: the same values as resolving the proxy and copying the native depth.

#version 450 core
#extension GL_EXT_samplerless_texture_functions : require

layout (binding = 0, set = 0) uniform texture2D src_depth;

layout (location = 0) in vec2 uv;
layout (location = 0) out float color;

void main() {
    const ivec2 size = textureSize(src_depth, 0);
    const ivec2 coord = min(ivec2(uv * vec2(size)), size - 1);
    color = texelFetch(src_depth, coord, 0).r;
}
