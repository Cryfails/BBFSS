// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r55_drawn-look-lines): the drawn look's menu texts, English and Russian, in one place.
// bbport_overlay.cpp shows them; renderer_vulkan/vk_drawn_look.cpp names with them why the look
// cannot run (Values::drawn_look_problem). bbport_menu_i18n.cpp's eight tables are looked up by
// the English text, and tests/test_settings.cpp checks that every text here is in all eight: a
// text changed here without its translations fails settings-test.
#pragma once

#include <cstring>

namespace BbSettings::DrawnLookTexts {

struct Text {
    const char* english;
    const char* russian;
};

inline constexpr Text Section{"Drawn look", "Рисованный стиль"};
inline constexpr Text Switch{"Drawn look (in development)", "Рисованный стиль (в разработке)"};
inline constexpr Text SwitchHint{
    "An optional hand-drawn look: brush strokes laid on the world's surfaces, bold on plain walls "
    "and floors, fine where there is detail, and ink lines along the edges of shapes. Fire, glows, "
    "fog, particles and the HUD stay as the game draws them. Colours are not changed; an ink line "
    "is the surface's own colour, darker. Applies at once. Not built yet: heavier ink on "
    "characters, lines on inner edges and painted shadow edges.",
    "Необязательный рисованный вид: мазки кисти ложатся на поверхности мира, крупные на ровных "
    "стенах и полах, мелкие там, где есть детали, а по краям форм идут контурные линии. Огонь, "
    "свечение, туман, частицы и интерфейс остаются такими, какими их рисует игра. Цвета не "
    "меняются; контурная линия — это собственный цвет поверхности, только темнее. Применяется "
    "сразу. Ещё не сделано: более густые контуры на персонажах, линии на внутренних рёбрах и "
    "рисованные края теней."};
inline constexpr Text Strength{"Drawn look strength", "Сила рисованного стиля"};
inline constexpr Text StrengthHint{
    "How much of the brush strokes is laid over the game's picture: 1 is the full look, lower "
    "values let more of the game's own picture through. At 0 there are no strokes; the ink lines "
    "stay while they are on. Applies at once.",
    "Насколько мазки кисти перекрывают изображение игры: 1 — стиль в полную силу, меньшие значения "
    "оставляют больше исходного изображения. При 0 мазков нет; контурные линии остаются, пока они "
    "включены. Применяется сразу."};
inline constexpr Text Ink{"Drawn look ink lines", "Контурные линии рисованного стиля"};
inline constexpr Text InkHint{
    "How dark the ink lines along the edges of shapes are: pillars, walls, steps and figures "
    "against what lies behind them. 0 is no lines. Lines grow thinner and fainter with distance "
    "and are gone beyond 120 m; fog covers them as it covers the world. Not drawn on frames the "
    "look paints right before the upscaler. While lines are drawn, the upscaler's extra sharpening "
    "is lowered by up to half. Colours are kept: a line is the surface's own colour, darker. "
    "Applies at once.",
    "Насколько темны контурные линии по краям форм: колонны, стены, ступени и фигуры на фоне того, "
    "что за ними. 0 — без линий. С расстоянием линии становятся тоньше и бледнее, а дальше 120 м "
    "исчезают; туман закрывает их так же, как и весь мир. Не рисуются в кадрах, где стиль "
    "накладывается прямо перед апскейлером. Пока линии рисуются, дополнительная резкость "
    "апскейлера снижается вплоть до половины. Цвета сохраняются: линия — это собственный цвет "
    "поверхности, только темнее. Применяется сразу."};
inline constexpr Text NoUpscaler{
    "the upscaler is not available (BB_UPSCALER=none, or this GPU cannot run it)",
    "апскейлер недоступен (BB_UPSCALER=none, или эта видеокарта не может его запустить)"};
inline constexpr Text NoPasses{
    "this GPU cannot run the passes",
    "эта видеокарта не может выполнить проходы"};
inline constexpr Text NotHalfFloat{
    "the scene colour is not RGBA16F",
    "цвет сцены не в формате RGBA16F"};
inline constexpr Text NoRoom{
    "not enough video memory at this render size",
    "недостаточно видеопамяти при этом разрешении рендеринга"};
inline constexpr Text ReducedNotStorage{
    "the reduced scene colour is not a storage image",
    "цвет уменьшенной сцены не является изображением для записи"};
inline constexpr Text NotStorage{
    "the scene colour is not a storage image",
    "цвет сцены не является изображением для записи"};
inline constexpr Text Unavailable{"Unavailable", "Недоступно"};

/// Why the look cannot run (Values::drawn_look_problem), as the renderer sets it.
inline constexpr const Text* Problems[] = {&NoUpscaler, &NoPasses, &NotHalfFloat, &NoRoom,
                                           &ReducedNotStorage, &NotStorage};
/// Every text of the look's menu rows, the problems included.
inline constexpr const Text* All[] = {&Section, &Switch, &SwitchHint, &Strength, &StrengthHint,
                                      &Ink, &InkHint, &NoUpscaler, &NoPasses, &NotHalfFloat,
                                      &NoRoom, &ReducedNotStorage, &NotStorage, &Unavailable};

/// The Russian of a problem the renderer set; `english` itself when it is none of them.
inline const char* RussianOf(const char* english) {
    for (const Text* text : Problems) {
        if (english && std::strcmp(english, text->english) == 0) {
            return text->russian;
        }
    }
    return english;
}

} // namespace BbSettings::DrawnLookTexts
