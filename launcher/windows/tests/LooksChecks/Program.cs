using System.IO;
using BloodborneLauncher.Core;

static void Require(bool condition, string message)
{
    if (!condition) throw new InvalidOperationException(message);
}

static bool Refused(string text)
{
    try
    {
        Looks.Parse(text);
        return false;
    }
    catch (FormatException)
    {
        return true;
    }
}

var knobs = Looks.Knobs.Select(k => k.Key).ToHashSet();
Require(knobs.Count == Looks.Knobs.Length, "A key is listed twice");
Require(knobs.All(k => k.StartsWith("graphics_") || k.StartsWith("effect_")), "A knob that is not a graphics value");
foreach (var knob in Looks.Knobs)
{
    Require(Looks.Normal(knob, knob.Default) != null, knob.Key + ": bad default");
    Require(knob.Min < knob.Max, knob.Key + ": bad range");
}
// The performance options (Graphics > Performance): lantern.ini settings that start at the engine's
// defaults, go into shared settings and are not part of a look.
var performance = new (string Key, string Start, string Other)[]
{
    ("graphics_rt_sun_half", "0", "1"), ("graphics_lamp_shadow_half", "0", "1"), ("graphics_rt_far_refit", "0", "1"),
    ("graphics_gi_reflections_fewer_rays", "0", "1"), ("object_motion_store", "auto", "small"),
    ("graphics_sun_far_shadows", "game", "rare"),
};
var performanceIni = new IniFile();
foreach (var option in performance)
{
    Require(IniFile.Defaults.Count(d => d.Key == option.Key) == 1 && IniFile.Defaults.Single(d => d.Key == option.Key).Value == option.Start,
        option.Key + ": not in the settings defaults once, at the engine's default");
    Require(!knobs.Contains(option.Key), option.Key + ": a performance option is part of a look");
    performanceIni.Set(option.Key, option.Other);
}
Require(Choices.MotionStore.Select(c => c.Value).SequenceEqual(new[] { "auto", "large", "small" }), "The motion vector store's values changed");
Require(Choices.IndexOf(Choices.MotionStore, "auto") == 0 && Choices.IndexOf(Choices.MotionStore, "") == 0, "The motion vector store does not start at auto");
Require(Choices.MotionStore.Skip(1).All(c => c.Note is { Length: > 0 }), "A motion vector store size does not say what it costs");
Require(Choices.SunFarShadows.Select(c => c.Value).SequenceEqual(new[] { "game", "alternate", "rare" }), "The far sun shadow values changed");
Require(Choices.IndexOf(Choices.SunFarShadows, "game") == 0 && Choices.IndexOf(Choices.SunFarShadows, "") == 0, "Far sun shadows does not start at the game's own");
Require(Choices.SunFarShadows[0].Note == null && Choices.SunFarShadows.Skip(1).All(c => c.Note is { Length: > 0 and <= 110 }),
    "A far sun shadow choice does not say what it gains in a note the row shows whole");
var performanceShared = SharedSettings.Parse(SharedSettings.ToCode(SharedSettings.Take(performanceIni, new LauncherSettings())));
Require(performance.All(p => performanceShared.Ini.TryGetValue(p.Key, out var shared) && shared == p.Other), "A performance option is left out of shared settings");
Console.WriteLine("PASS performance options: " + performance.Length + " settings at their defaults, in shared settings, in no look");

// Previous engine paths (More > Engine): a troubleshooting switch. It starts off and is in no
// look. It is a tested setting at off, as Legacy shader compiler and Occlusion culling are: a
// beta's "use the tested settings" offer names it while it is on and turns it off. It stays on
// the PC it was set on: shared settings do not carry it and a code that names it does not set it.
const string previousPaths = "engine_previous_paths";
Require(IniFile.Defaults.Count(d => d.Key == previousPaths) == 1 && IniFile.Defaults.Single(d => d.Key == previousPaths).Value == "0",
    previousPaths + ": not in the settings defaults once, off");
Require(!knobs.Contains(previousPaths), previousPaths + ": the troubleshooting switch is part of a look");
Require(TestedSettings.All.Count(t => t.Key == previousPaths) == 1 && TestedSettings.All.Single(t => t.Key == previousPaths) is { Tested: "0", Default: "0", Launcher: false },
    previousPaths + ": not a tested setting once, off, read from lantern.ini");
Require(TestedSettings.All.All(t => t.Key != "graphics_sun_far_shadows"), "Far sun shadows is a tested setting: the other performance options are not");
Require(TestedSettings.Differences(performanceIni, new LauncherSettings()).All(t => t.Key != previousPaths), previousPaths + ": off is listed against the tested settings");
performanceIni.Set(previousPaths, "1");
Require(performanceIni.Flag(previousPaths), previousPaths + ": not kept as set");
Require(TestedSettings.Differences(performanceIni, new LauncherSettings()).Any(t => t.Key == previousPaths), previousPaths + ": on is not listed against the tested settings");
var withPrevious = SharedSettings.Parse(SharedSettings.ToCode(SharedSettings.Take(performanceIni, new LauncherSettings())));
Require(!withPrevious.Ini.ContainsKey(previousPaths), "Shared settings carry the troubleshooting switch");
Require(withPrevious.Ini.TryGetValue("graphics_sun_far_shadows", out var sharedFar) && sharedFar == "rare", "Far sun shadows is left out of shared settings");
var namesPrevious = SharedSettings.Parse("{\"bbpc_settings\":1,\"ini\":{\"engine_previous_paths\":\"1\",\"graphics_sun_far_shadows\":\"alternate\"},\"launcher\":{\"engine_previous_paths\":true}}");
Require(namesPrevious.Ini.Count == 1 && namesPrevious.Ini["graphics_sun_far_shadows"] == "alternate" && namesPrevious.Launcher.Count == 0,
    "A settings code can turn the troubleshooting switch on");
Console.WriteLine("PASS previous engine paths: off by default, in no look, a tested setting at off, not carried or set by shared settings");

foreach (var look in Looks.Presets)
{
    Require(look.BuiltIn && look.Description.Length > 0, look.Name + ": a preset says what it costs");
    Require(look.Values.Keys.All(knobs.Contains), look.Name + ": a preset sets a key outside the list");
}

var values = new Dictionary<string, string> { ["effect_gi"] = "1", ["graphics_gi_strength"] = "7.5" };
var original = new Looks.Look("Mine", "Someone", values);
var fromJson = Looks.Parse(Looks.ToJson(original));
var fromCode = Looks.Parse("here it is: " + Looks.ToCode(original) + " enjoy");
foreach (var parsed in new[] { fromJson, fromCode })
{
    Require(parsed.Name == "Mine" && parsed.Author == "Someone", "Name or author lost");
    Require(parsed.Values.Count == 2 && parsed.Values["graphics_gi_strength"] == "7.5", "Values lost");
    Require(!parsed.BuiltIn, "An import must not read as a preset");
}

const string Good = "{\"lantern_look\":1,\"name\":\"x\",\"author\":\"y\",\"values\":{\"effect_gi\":\"1\"}}";
Require(!Refused(Good), "A good look was refused");
Require(Refused(Good.Replace("effect_gi", "BB_USER_DIR")), "An env variable got through");
Require(Refused(Good.Replace("effect_gi", "upscaler")), "A setting outside the list got through");
Require(Refused(Good.Replace("effect_gi", "exp_guest_in_place")), "An engine switch got through");
Require(Refused(Good.Replace("effect_gi", "../../saves")), "A path got through");
Require(Refused(Good.Replace("\"lantern_look\":1", "\"lantern_look\":2")), "A newer version got through");
Require(Refused(Good.Replace("\"name\":\"x\"", "\"run\":\"calc.exe\"")), "An unknown field got through");
Require(Refused(Good.Replace("\"1\"", "\"NaN\"")), "NaN got through");
Require(Refused(Good.Replace("\"1\"", "\"Infinity\"")), "Infinity got through");
Require(Refused(Good.Replace("\"1\"", "\"lots\"")), "Text got through");
Require(Refused(Good.Replace("\"1\"", "{\"a\":1}")), "An object got through");
Require(Refused("not a look"), "Plain text got through");
Require(Refused("{"), "Broken JSON got through");
Require(Refused(new string(' ', 64 * 1024) + Good), "A huge text got through");
Require(Refused(Looks.CodePrefix + "!!!!"), "A broken code got through");

var clampHigh = Looks.Parse(Good.Replace("effect_gi\":\"1\"", "graphics_gi_strength\":\"999\""));
Require(clampHigh.Values["graphics_gi_strength"] == "12", "No clamp above");
var clampLow = Looks.Parse(Good.Replace("effect_gi\":\"1\"", "graphics_contrast\":-5"));
Require(clampLow.Values["graphics_contrast"] == "0.5", "No clamp below");
var whole = Looks.Parse(Good.Replace("effect_gi\":\"1\"", "graphics_shadow_resolution\":\"7\""));
Require(whole.Values["graphics_shadow_resolution"] == "2", "No clamp of a level");

using (var packed = new MemoryStream())
{
    using (var deflate = new System.IO.Compression.DeflateStream(packed, System.IO.Compression.CompressionLevel.SmallestSize))
        deflate.Write(new byte[4 * 1024 * 1024]);
    var bomb = Looks.CodePrefix + Convert.ToBase64String(packed.ToArray()).TrimEnd('=').Replace('+', '-').Replace('/', '_');
    Require(Refused(bomb), "A zip bomb got through");
}

var odd = Looks.Parse(Good.Replace("\"x\"", "\"a\\u202Eb\\u0007c" + new string('n', 200) + "\""));
Require(odd.Name.Length <= 48 && !odd.Name.Contains('‮') && !odd.Name.Contains('\a'), "A name was not cleaned");

var steady = EngineSwitches.All.SingleOrDefault(s => s.Env == "BB_VOLUMETRIC_STEADY");
Require(steady != null, "The steady sunlight color switch is missing from the Engine page");
Require(steady!.Group == EngineSwitches.Graphics, "The steady sunlight color switch is not in the Graphics group");
Require(steady.Kind == SwitchKind.Toggle && steady.Default == steady.On, "The steady sunlight color switch is not on by default");
Require(!Looks.Knobs.Any(k => k.Key.Contains("steady", StringComparison.OrdinalIgnoreCase) || k.Key == steady.Env),
    "A look knob uses the steady sunlight color switch");
Require(!Choices.Effects.Any(e => e.Key.Contains("steady", StringComparison.OrdinalIgnoreCase) || e.Key == steady.Env),
    "An effect row uses the steady sunlight color switch");

var ini = new IniFile();
ini.Set("graphics_bloom", "2");
ini.Set("upscaler", "dlss");
Require(!Looks.IsCurrent(Looks.Presets[0], ini), "The original look does not read as current");
var mine = Looks.FromCurrent(ini, "Now", "");
Require(mine.Values.Count == 1 && mine.Values["graphics_bloom"] == "2", "FromCurrent took the wrong values");
Require(Looks.IsCurrent(mine, ini), "A look of the current values reads as current");

// Steady fog is a choice between two kinds of fog, not part of a look; it is an Engine > Graphics switch
// (BB_POINT_FOG_STEADY) and starts on, as the engine's default does.
var steadyFog = EngineSwitches.All.SingleOrDefault(e => e.Env == "BB_POINT_FOG_STEADY");
Require(steadyFog != null, "Steady lamp fog is not an Engine switch");
Require(steadyFog!.Group == EngineSwitches.Graphics, "Steady lamp fog is not in the Engine Graphics group");
Require(steadyFog.Default == steadyFog.On, "Steady lamp fog does not start on");

Console.WriteLine("PASS looks: " + Looks.Knobs.Length + " knobs, " + Looks.Presets.Count + " presets");
