// SPDX-License-Identifier: Apache-2.0
// Copyright 2023 Sony Interactive Entertainment.
// Adapted from Bend Studio's Screen Space Shadows for Bloodborne's shadow constants.
#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>

namespace Vulkan::BendSss {

constexpr int WaveSize = 64;

struct DispatchData {
    std::array<int, 3> wave_count{};
    std::array<int, 2> wave_offset{};
};

struct DispatchList {
    std::array<float, 4> light_coordinate{};
    std::array<DispatchData, 9> dispatches{};
    int dispatch_count = 0;
};

inline DispatchList BuildDispatchList(const std::array<float, 4>& light_projection,
                                      int width, int height) {
    DispatchList result{};
    float xy_light_w = light_projection[3];
    const float precision_limit = 0.000002f * float(WaveSize);
    if (xy_light_w >= 0.0f && xy_light_w < precision_limit) {
        xy_light_w = precision_limit;
    } else if (xy_light_w < 0.0f && xy_light_w > -precision_limit) {
        xy_light_w = -precision_limit;
    }

    result.light_coordinate[0] =
        (light_projection[0] / xy_light_w * 0.5f + 0.5f) * float(width);
    result.light_coordinate[1] =
        (light_projection[1] / xy_light_w * -0.5f + 0.5f) * float(height);
    result.light_coordinate[2] = light_projection[3] == 0.0f
                                     ? 0.0f
                                     : light_projection[2] / light_projection[3];
    result.light_coordinate[3] = light_projection[3] > 0.0f ? 1.0f : -1.0f;

    const int light_x = int(result.light_coordinate[0] + 0.5f);
    const int light_y = int(result.light_coordinate[1] + 0.5f);
    const std::array<int, 4> biased_bounds{
        -light_x,
        -(height - light_y),
        width - light_x,
        light_y,
    };

    for (int quadrant = 0; quadrant < 4; ++quadrant) {
        const bool vertical = quadrant == 0 || quadrant == 3;
        const std::array<int, 4> bounds{
            std::max(0, ((quadrant & 1) ? biased_bounds[0] : -biased_bounds[2])) / WaveSize,
            std::max(0, ((quadrant & 2) ? biased_bounds[1] : -biased_bounds[3])) / WaveSize,
            std::max(0, (((quadrant & 1) ? biased_bounds[2] : -biased_bounds[0]) +
                         WaveSize * (vertical ? 1 : 2) - 1)) / WaveSize,
            std::max(0, (((quadrant & 2) ? biased_bounds[3] : -biased_bounds[1]) +
                         WaveSize * (vertical ? 2 : 1) - 1)) / WaveSize,
        };
        if (bounds[2] <= bounds[0] || bounds[3] <= bounds[1]) {
            continue;
        }

        const int bias_x = quadrant >= 2 ? 1 : 0;
        const int bias_y = quadrant == 1 || quadrant == 3 ? 1 : 0;
        auto& dispatch = result.dispatches[result.dispatch_count++];
        dispatch.wave_count = {WaveSize, bounds[2] - bounds[0], bounds[3] - bounds[1]};
        dispatch.wave_offset = {
            ((quadrant & 1) ? bounds[0] : -bounds[2]) + bias_x,
            ((quadrant & 2) ? -bounds[3] : bounds[1]) + bias_y,
        };

        int axis_delta = biased_bounds[0] - biased_bounds[1];
        if (quadrant == 1) {
            axis_delta = biased_bounds[2] + biased_bounds[1];
        } else if (quadrant == 2) {
            axis_delta = -biased_bounds[0] - biased_bounds[3];
        } else if (quadrant == 3) {
            axis_delta = -biased_bounds[2] + biased_bounds[3];
        }
        axis_delta = (axis_delta + WaveSize - 1) / WaveSize;
        if (axis_delta <= 0) {
            continue;
        }

        auto& split = result.dispatches[result.dispatch_count++];
        split = dispatch;
        if (quadrant == 0) {
            split.wave_count[2] = std::min(dispatch.wave_count[2], axis_delta);
            dispatch.wave_count[2] -= split.wave_count[2];
            split.wave_offset[1] = dispatch.wave_offset[1] + dispatch.wave_count[2];
            --split.wave_offset[0];
            ++split.wave_count[1];
        } else if (quadrant == 1) {
            split.wave_count[1] = std::min(dispatch.wave_count[1], axis_delta);
            dispatch.wave_count[1] -= split.wave_count[1];
            split.wave_offset[0] = dispatch.wave_offset[0] + dispatch.wave_count[1];
            ++split.wave_count[2];
        } else if (quadrant == 2) {
            split.wave_count[1] = std::min(dispatch.wave_count[1], axis_delta);
            dispatch.wave_count[1] -= split.wave_count[1];
            dispatch.wave_offset[0] += split.wave_count[1];
            ++split.wave_count[2];
            --split.wave_offset[1];
        } else {
            split.wave_count[2] = std::min(dispatch.wave_count[2], axis_delta);
            dispatch.wave_count[2] -= split.wave_count[2];
            dispatch.wave_offset[1] += split.wave_count[2];
            ++split.wave_count[1];
        }

        if (split.wave_count[1] <= 0 || split.wave_count[2] <= 0) {
            split = result.dispatches[--result.dispatch_count];
        }
        if (dispatch.wave_count[1] <= 0 || dispatch.wave_count[2] <= 0) {
            dispatch = result.dispatches[--result.dispatch_count];
        }
    }

    for (int i = 0; i < result.dispatch_count; ++i) {
        result.dispatches[i].wave_offset[0] *= WaveSize;
        result.dispatches[i].wave_offset[1] *= WaveSize;
    }
    if (result.light_coordinate[0] >= 0.0f && result.light_coordinate[0] < float(width) &&
        result.light_coordinate[1] >= 0.0f && result.light_coordinate[1] < float(height)) {
        auto& center = result.dispatches[result.dispatch_count++];
        center.wave_count = {1, 1, 1};
    }
    return result;
}

using Mat4 = std::array<std::array<float, 4>, 4>;
using Vec4 = std::array<float, 4>;

inline bool Invert(const Mat4& matrix, Mat4& inverse) {
    Mat4 a = matrix;
    inverse = {};
    for (int i = 0; i < 4; ++i) {
        inverse[i][i] = 1.0f;
    }
    for (int column = 0; column < 4; ++column) {
        int pivot = column;
        for (int row = column + 1; row < 4; ++row) {
            if (std::abs(a[row][column]) > std::abs(a[pivot][column])) {
                pivot = row;
            }
        }
        if (!(std::abs(a[pivot][column]) > 1e-12f)) {
            return false;
        }
        if (pivot != column) {
            std::swap(a[pivot], a[column]);
            std::swap(inverse[pivot], inverse[column]);
        }
        const float scale = 1.0f / a[column][column];
        for (int i = 0; i < 4; ++i) {
            a[column][i] *= scale;
            inverse[column][i] *= scale;
        }
        for (int row = 0; row < 4; ++row) {
            if (row == column) {
                continue;
            }
            const float factor = a[row][column];
            for (int i = 0; i < 4; ++i) {
                a[row][i] -= factor * a[column][i];
                inverse[row][i] -= factor * inverse[column][i];
            }
        }
    }
    return true;
}

inline Vec4 Multiply(const Vec4& row, const Mat4& matrix) {
    Vec4 result{};
    for (int column = 0; column < 4; ++column) {
        for (int i = 0; i < 4; ++i) {
            result[column] += row[i] * matrix[i][column];
        }
    }
    return result;
}

inline Vec4 Multiply(const Mat4& matrix, const Vec4& vector) {
    Vec4 result{};
    for (int row = 0; row < 4; ++row) {
        for (int i = 0; i < 4; ++i) {
            result[row] += matrix[row][i] * vector[i];
        }
    }
    return result;
}

inline DispatchList BuildDirectionalDispatchList(const float* constants, int width, int height,
                                                 float flip = 1.0f) {
    if (!constants || width <= 0 || height <= 0) {
        return {};
    }
    Mat4 inverse_projection{};
    for (int row = 0; row < 4; ++row) {
        for (int column = 0; column < 4; ++column) {
            inverse_projection[row][column] = constants[row * 4 + column];
        }
    }
    Mat4 projection{};
    if (!Invert(inverse_projection, projection)) {
        return {};
    }

    Vec4 light_u{}, light_v{}, light_z{};
    for (int i = 0; i < 4; ++i) {
        light_u[i] = constants[16 + i];
        light_v[i] = constants[20 + i];
        light_z[i] = constants[24 + i];
    }
    light_u = Multiply(light_u, projection);
    light_v = Multiply(light_v, projection);
    light_z = Multiply(light_z, projection);

    Vec4 direction{
        light_u[1] * light_v[2] - light_u[2] * light_v[1],
        light_u[2] * light_v[0] - light_u[0] * light_v[2],
        light_u[0] * light_v[1] - light_u[1] * light_v[0],
        0.0f,
    };
    const float length = std::sqrt(direction[0] * direction[0] +
                                   direction[1] * direction[1] +
                                   direction[2] * direction[2]);
    if (!(length > 1e-12f) || !std::isfinite(length)) {
        return {};
    }
    for (int i = 0; i < 3; ++i) {
        direction[i] /= length;
    }
    const float depth_direction = light_z[0] * direction[0] + light_z[1] * direction[1] +
                                  light_z[2] * direction[2];
    if (depth_direction > 0.0f) {
        direction[0] = -direction[0];
        direction[1] = -direction[1];
        direction[2] = -direction[2];
    }
    direction[0] *= flip;
    direction[1] *= flip;
    direction[2] *= flip;

    const Vec4 light_projection = Multiply(projection, direction);
    if (!std::all_of(light_projection.begin(), light_projection.end(),
                     [](float value) { return std::isfinite(value); })) {
        return {};
    }
    return BuildDispatchList(light_projection, width, height);
}

} // namespace Vulkan::BendSss
