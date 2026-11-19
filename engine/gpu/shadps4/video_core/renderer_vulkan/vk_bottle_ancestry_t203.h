#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <span>
#ifdef BB_TEST_SHARED_POST_GRAPH
#include <tuple>
#endif

namespace BottleAncestry {

constexpr std::size_t MaxEvents = 32;
constexpr std::size_t MaxInputs = 8;
#ifdef BB_TEST_SHARED_POST_GRAPH
constexpr std::size_t ProbeCount = 7;
#else
constexpr std::size_t ProbeCount = 2; // receiver, opaque control
#endif

enum class Proof : std::uint8_t { Unknown, Failed, Known };
enum class Stage : std::uint8_t { SceneRgb, Ui, Display, Prepare, Swapchain, Present
#ifdef BB_TEST_SHARED_POST_GRAPH
    , HdrClamp, LdrComposite
#endif
};
enum class Kind : std::uint8_t { Merge, Raster, Transfer, Compute, Clear, Overwrite, Ui, Display, Prepare, Swapchain, Present };
enum class Role : std::uint8_t { Unknown, BaseRgb, AuxiliaryRgb, Lut, PriorDestination, Other };
enum class Format : std::uint8_t { Unknown, Rgba16Float, Rgba8Unorm, Other };
enum class BindStage : std::uint8_t { Unknown, Fragment, Compute, Transfer, Attachment, Host };
enum class Prior : std::uint8_t { Unknown, Discard, Blend };

using Coverage = std::array<Proof, ProbeCount>;

#ifdef BB_TEST_SHARED_POST_GRAPH
enum class Client : std::uint8_t { Bottle, Sewer };
enum class Arm : std::uint8_t { On, Off, Mixed };
enum class ProbeRole : std::uint8_t { Receiver, Opaque0, Opaque1, Wet0, Wet1, Dry, Neighbor, LastOn, Vacated0, Vacated1 };
enum class PostStep : std::uint8_t { Unknown, Clamp, Composite, Grade, Glow, Carry };

struct ScopeKey {
    std::uint64_t request{}, scene{}, load{}, targets{}, queue{}, timeline{};
    std::uint32_t frame{};
    Client client{};
    Arm arm{};
    char checkpoint{}; // Sewer A/B/C. Bottle uses its scene ordinal.
    bool operator==(const ScopeKey&) const = default;
};

struct ProbeRegion {
    ProbeRole role{};
    std::uint32_t x{}, y{}, width{}, height{};
};

struct Scope {
    ScopeKey key{};
    std::uint32_t width{}, height{}, count{};
    std::array<ProbeRegion, ProbeCount> probes{};

    bool Valid() const {
        if (!key.request || !key.scene || !key.load || !key.targets ||
            key.arm > Arm::Mixed || !count || count > probes.size() || !width || !height) return false;
        std::uint32_t roles{};
        const auto bit = [](ProbeRole role) { return 1u << std::uint32_t(role); };
        for (std::uint32_t i = 0; i < count; ++i) {
            const auto& probe = probes[i];
            if (probe.role > ProbeRole::Vacated1 || !probe.width || !probe.height ||
                probe.width > width || probe.height > height || probe.x > width - probe.width ||
                probe.y > height - probe.height || (roles & bit(probe.role))) return false;
            roles |= bit(probe.role);
        }
        switch (key.client) {
        case Client::Bottle: {
            constexpr std::array wet{ProbeRole::Wet0, ProbeRole::Wet1, ProbeRole::Dry};
            for (const auto role : wet) if (roles & bit(role)) return false;
            const auto needed = bit(ProbeRole::Receiver) | bit(ProbeRole::Opaque0);
            return !key.checkpoint && (roles & needed) == needed;
        }
        case Client::Sewer: {
            const auto needed = bit(ProbeRole::Wet0) | bit(ProbeRole::Wet1) | bit(ProbeRole::Dry);
            return key.checkpoint >= 'A' && key.checkpoint <= 'C' && !(roles & bit(ProbeRole::Receiver)) &&
                   (roles & needed) == needed;
        }
        }
        return false;
    }
};

struct IssueOrder {
    std::uint64_t queue{}, timeline{}, tick{}, submission{}, command{}, incarnation{};
    std::uint32_t segment{}, ordinal{};
    Proof submitted{}, dependencies{};

    bool Named() const { return queue && timeline && tick && submission && command && incarnation && ordinal; }
    auto Position() const { return std::tuple{submission, segment, ordinal}; }
};
#endif

struct Subresource {
    std::uint16_t mip{}, mips{}, layer{}, layers{};
    std::uint8_t aspects{};

    bool operator==(const Subresource&) const = default;
    bool Valid() const { return mips && layers && aspects; }

    bool Overlaps(const Subresource& other) const {
        return (aspects & other.aspects) &&
               mip < other.mip + other.mips && other.mip < mip + mips &&
               layer < other.layer + other.layers && other.layer < layer + layers;
    }
};

// backing identifies physical alias storage. view identifies the effective bound view.
// Use ascending nonzero allocation serials per backing and content serials per allocation.
struct ImageVersion {
    std::uint64_t backing{}, view{}, uid{}, allocation{}, content{};
    Subresource range{};
    Format format{};

    bool operator==(const ImageVersion&) const = default;
    bool Valid() const {
        return backing && view && uid && allocation && content && range.Valid() &&
               format != Format::Unknown;
    }

    bool Aliases(const ImageVersion& other) const {
        return backing == other.backing && range.Overlaps(other.range);
    }
};

struct Input {
    ImageVersion image{};
    Coverage read{}; // Actual mapped source footprint, per corresponding probe.
    Role role{};
    BindStage stage{};
    std::uint8_t set{}, binding{};
    Proof access{}; // Exact effective descriptor (or load), backed by the issuing route.
    bool external{}; // Independently witnessed external input. Cannot hide a tracked writer.
    std::uint64_t writer_view{}; // Optional mapped producing view, proved by adapter.
#ifdef BB_TEST_SHARED_POST_GRAPH
    std::uint32_t element{};
    Proof sampler{}; // Actual effective sampler or proven nonsampling load.
    Coverage contribution{}; // Known nonzero RGB contribution at the registered patch.
#endif
};

struct Event {
    ImageVersion output{};
    Coverage written{}; // View/extent/layer/scissor/mask and known written RGB coverage.
    Coverage untouched{}; // Proved spatial exclusion, retaining an exact prior destination.
    Stage carry{}; // Raster/Transfer/Compute can carry an already reached stage forward.
    std::uint64_t order{}, permutation{};
    std::uint32_t shader{};
    Kind kind{};
    Proof issued{}, pipeline{}; // Queued issue and effective pipeline/attachment contract.
    Proof boundary{}; // Existing scene/arm/phase-2 and actual UI/Prepare/acquire/present guards.
    Prior prior{}; // Effective load/blend behavior for raster; Discard when no prior needed.
#ifdef BB_TEST_SHARED_POST_GRAPH
    ScopeKey scope{};
    IssueOrder actual{};
    PostStep step{};
    Proof recipe{}; // Proven effective program and permutation (including substitutions).
    std::uint32_t required_slots{};
#endif
};

enum Fact : std::uint32_t {
    Issue = 1u << 0, Pipeline = 1u << 1, Destination = 1u << 2, Semantic = 1u << 3,
    InputAccess = 1u << 4, Writer = 1u << 5, CoverageFact = 1u << 6, PriorFact = 1u << 7,
    StageFact = 1u << 8, Alias = 1u << 9, Order = 1u << 10,
    Boundary = 1u << 12, CachedFormat = 1u << 13, CachedPermutation = 1u << 14,
#ifdef BB_TEST_SHARED_POST_GRAPH
    ScopeFact = 1u << 15, EffectiveRecipe = 1u << 16, Sampler = 1u << 17, Contribution = 1u << 18,
#endif
};

struct Facts {
    // Multiple input slots/probes can contribute different results to the same fact.
    std::uint32_t known{}, failed{}, unknown{};
    void Add(Fact fact, Proof proof) {
        switch (proof) {
        case Proof::Known: known |= fact; break;
        case Proof::Failed: failed |= fact; break;
        case Proof::Unknown: unknown |= fact; break;
        }
    }
};

struct Lineage {
    Proof proof{};
    Stage stage{};
    std::uint32_t base{}, auxiliary{}; // Writer event bits, with auxiliary kept separate.
};

using ProbeLineage = std::array<Lineage, ProbeCount>;

struct ReadResult {
    ProbeLineage probes{};
    bool obstructed{}; // Missing data from a possible intervening writer.
    Proof writer{}, alias{};
};

struct Entry {
    Event event{};
    std::array<Input, MaxInputs> inputs{};
    std::array<ProbeLineage, MaxInputs> input_lineage{};
    std::size_t input_count{};
    Facts facts{};
    Proof fresh{};
    ProbeLineage result{};
};

struct CacheContract {
    std::uint32_t shader;
    std::uint64_t permutation;
    Format format;
};

constexpr std::array CacheContracts{
    CacheContract{0xccbf44a6, 0x00000ccc53f28aa5, Format::Rgba16Float},
    CacheContract{0x5e67d866, 0x000005e77fc38f59, Format::Rgba8Unorm},
    CacheContract{0xccb08339, 0x00000ccb7f8692d5, Format::Rgba8Unorm},
    CacheContract{0xed4c7668, 0x00000ed5993eb777, Format::Rgba8Unorm},
    CacheContract{0x8c08444c, 0x000008c1a734f9b1, Format::Rgba8Unorm},
};

inline const CacheContract* FindCacheContract(std::uint32_t shader) {
    for (const auto& contract : CacheContracts) {
        if (shader == contract.shader) {
            return &contract;
        }
    }
    return nullptr;
}

inline Role CachedRole(const CacheContract& contract, const Input& input) {
    if (input.stage == BindStage::Attachment) {
        return Role::PriorDestination;
    }
    if (input.stage != BindStage::Fragment || input.set != 0) {
        return Role::Unknown;
    }
    switch (contract.shader) {
    case 0xccbf44a6: return input.binding == 0 ? Role::BaseRgb : Role::Other;
    case 0x5e67d866:
    case 0xccb08339: return input.binding == 1 || input.binding == 2 ? Role::BaseRgb : Role::Other;
    case 0xed4c7668:
        if (input.binding == 1) {
            return Role::Lut;
        }
        return input.binding == 0 ? Role::BaseRgb : Role::Other;
    case 0x8c08444c: return input.binding == 3 ? Role::AuxiliaryRgb : Role::Other;
    default: return Role::Unknown;
    }
}

inline Proof All(Proof lhs, Proof rhs) {
    if (lhs == Proof::Failed || rhs == Proof::Failed) {
        return Proof::Failed;
    }
    return lhs == Proof::Known && rhs == Proof::Known ? Proof::Known : Proof::Unknown;
}

inline Proof Any(Proof lhs, Proof rhs) {
    if (lhs == Proof::Known || rhs == Proof::Known) {
        return Proof::Known;
    }
    return lhs == Proof::Unknown || rhs == Proof::Unknown ? Proof::Unknown : Proof::Failed;
}

inline ProbeLineage Uniform(Proof proof) {
#ifdef BB_TEST_SHARED_POST_GRAPH
    ProbeLineage out{};
    out.fill(Lineage{proof});
    return out;
#else
    return {Lineage{proof}, Lineage{proof}};
#endif
}

class SceneTrace {
public:
    // Supply every possibly overlapping write/invalidation, even if unrelated to this pass.
    // A known skip is Failed. Unknown issue with plausible alias shadows the previous write.
    // A missing destination on a potentially relevant write is treated as possibly any alias.
#ifdef BB_TEST_SHARED_POST_GRAPH
    bool Record(const Event& event, std::span<const Input> inputs = {}, std::size_t omitted = 0);
#else
    bool Record(const Event& event, std::span<const Input> inputs = {});
#endif
    ReadResult Read(const ImageVersion& image) const { return ReadBefore(image, count_); }
    ProbeLineage PresentResult() const;
    std::span<const Entry> Entries() const { return {entries_.data(), count_}; }

    std::uint64_t Scene() const { return scene_; }
    std::uint32_t OmittedEvents() const { return omitted_events_; }
    std::uint32_t OmittedInputs() const { return omitted_inputs_; }
    bool Overflowed() const { return omitted_events_ || omitted_inputs_; }
#ifdef BB_TEST_SHARED_POST_GRAPH
    bool Begin(Scope scope) {
        if (scene_ || !scope.Valid()) return false;
        scope_ = scope;
        scene_ = scope.key.scene;
        return true;
    }
    const Scope& Registration() const { return scope_; }
    std::uint32_t ForeignEvents() const { return foreign_events_; }
#endif

private:
    friend class SetupTrace;
    ReadResult ReadBefore(const ImageVersion& image, std::size_t upper) const;

    std::array<Entry, MaxEvents> entries_{};
    std::uint64_t scene_{};
    std::size_t count_{};
    std::uint32_t omitted_events_{}, omitted_inputs_{};
    bool invalid_order_{};
#ifdef BB_TEST_SHARED_POST_GRAPH
    std::size_t ActiveProbes() const { return scope_.count ? scope_.count : 2; }
    Scope scope_{};
    IssueOrder last_issued_{};
    std::uint32_t foreign_events_{};
#endif
};

class SetupTrace {
public:
    enum class Mode : std::uint8_t { Off, On };

    // Call after the adapter has witnessed the effective native arm and selected scene.
    SceneTrace* Select(Mode mode, std::uint64_t scene) {
        const auto slot = static_cast<std::size_t>(mode);
        if (!scene || slot >= scenes_.size() || scenes_[slot].scene_ ||
            scenes_[1 - slot].scene_ == scene) {
            ++refused_scenes_;
            return nullptr;
        }
        scenes_[slot].scene_ = scene;
        return &scenes_[slot];
    }

    const SceneTrace& Get(Mode mode) const { return scenes_[static_cast<std::size_t>(mode)]; }
    std::uint32_t RefusedScenes() const { return refused_scenes_; }

private:
    std::array<SceneTrace, 2> scenes_{};
    std::uint32_t refused_scenes_{};
};

inline ReadResult SceneTrace::ReadBefore(const ImageVersion& image, std::size_t upper) const {
    if (Overflowed() || invalid_order_ || !image.Valid()) {
        return {{}, true};
    }
    while (upper) {
        const auto& entry = entries_[--upper];
        const auto& event = entry.event;
        if (event.kind == Kind::Present || event.issued == Proof::Failed) {
            continue;
        }
        if (!event.output.backing || (event.output.backing == image.backing &&
                                     !event.output.range.Valid())) {
            return {{}, true};
        }
        if (!event.output.Aliases(image)) {
            continue;
        }
        if (event.issued == Proof::Unknown || !event.output.Valid() ||
            entry.fresh == Proof::Unknown) {
            return {{}, true};
        }
        if (event.output == image && entry.fresh == Proof::Known) {
            return {entry.result, false, Proof::Known, Proof::Known};
        }
        return {Uniform(Proof::Failed), false, Proof::Failed, Proof::Failed};
    }
    return {};
}

#ifdef BB_TEST_SHARED_POST_GRAPH
inline bool SceneTrace::Record(const Event& event, std::span<const Input> inputs, std::size_t omitted) {
#else
inline bool SceneTrace::Record(const Event& event, std::span<const Input> inputs) {
#endif
    if (!scene_) {
        return false;
    }
#ifdef BB_TEST_SHARED_POST_GRAPH
    const bool scoped = scope_.count != 0;
    if (scoped && event.scope != scope_.key) {
        ++foreign_events_;
        return false;
    }
#endif
#ifdef BB_TEST_SHARED_POST_GRAPH
    const auto missing = scoped ? omitted + (inputs.size() > MaxInputs ? inputs.size() - MaxInputs : 0) : 0;
    if (scoped && inputs.size() > MaxInputs) inputs = inputs.first(MaxInputs);
    if ((!scoped && Overflowed()) || count_ == MaxEvents || inputs.size() > MaxInputs) {
#else
    if (Overflowed() || count_ == MaxEvents || inputs.size() > MaxInputs) {
#endif
        ++omitted_events_;
#ifdef BB_TEST_SHARED_POST_GRAPH
        omitted_inputs_ += static_cast<std::uint32_t>(missing);
#endif
        if (inputs.size() > MaxInputs) {
            omitted_inputs_ += static_cast<std::uint32_t>(inputs.size() - MaxInputs);
        }
        return false;
    }

    const auto index = count_++;
    const auto event_bit = std::uint32_t{1} << index;
    auto& entry = entries_[index];
    entry.event = event;
    entry.input_count = inputs.size();
    auto& facts = entry.facts;
    const bool ordered = event.order && (!index || entries_[index - 1].event.order < event.order);
    facts.Add(Order, ordered ? Proof::Known : Proof::Failed);
#ifdef BB_TEST_SHARED_POST_GRAPH
    Proof actual_order = Proof::Known;
    if (scoped) {
        facts.Add(ScopeFact, Proof::Known);
        if (event.issued != Proof::Failed) {
            const auto& actual = event.actual;
            actual_order = All(actual.submitted, actual.dependencies);
            if (!actual.Named() || !scope_.key.queue || !scope_.key.timeline)
                actual_order = All(actual_order, Proof::Unknown);
            if ((scope_.key.queue && actual.queue && actual.queue != scope_.key.queue) ||
                (scope_.key.timeline && actual.timeline && actual.timeline != scope_.key.timeline))
                actual_order = Proof::Failed;
            if (actual.Named() && actual.submitted == Proof::Known && actual_order != Proof::Failed) {
                if (last_issued_.Named() && (actual.Position() <= last_issued_.Position() ||
                    actual.tick < last_issued_.tick ||
                    (actual.submission == last_issued_.submission && actual.segment == last_issued_.segment &&
                     (actual.command != last_issued_.command || actual.incarnation != last_issued_.incarnation)))) {
                    actual_order = Proof::Failed;
                }
                if (actual_order != Proof::Failed) last_issued_ = actual;
            }
        }
        facts.Add(Order, actual_order);
    }
#endif
    facts.Add(Issue, event.issued);
    facts.Add(Pipeline, event.pipeline);
    const bool has_output = event.kind != Kind::Present;
    const Proof destination = event.output.Valid() ? Proof::Known : Proof::Unknown;
    facts.Add(Destination, destination);
    const auto* cache = event.kind == Kind::Raster ? FindCacheContract(event.shader) : nullptr;
    const Proof cached_format = !cache || cache->format == event.output.format ? Proof::Known :
                                event.output.format == Format::Unknown ? Proof::Unknown : Proof::Failed;
    const Proof cached_permutation = !cache || cache->permutation == event.permutation ?
                                     Proof::Known : event.permutation ? Proof::Failed : Proof::Unknown;
    if (cache) {
        facts.Add(CachedFormat, cached_format);
        facts.Add(CachedPermutation, cached_permutation);
    }

    Proof fresh = Proof::Known;
    if (has_output && event.output.Valid()) {
        for (std::size_t i = 0; i < index; ++i) {
            const auto& previous = entries_[i].event;
            if (previous.kind != Kind::Present && previous.issued != Proof::Failed &&
                previous.output.Aliases(event.output) &&
                (previous.output.allocation > event.output.allocation ||
                 (previous.output.allocation == event.output.allocation &&
                  previous.output.content >= event.output.content))) {
                fresh = All(fresh, previous.issued == Proof::Known ? Proof::Failed : Proof::Unknown);
            }
        }
    }
    entry.fresh = fresh;
    facts.Add(Alias, fresh);
    invalid_order_ |= !ordered;

    const bool raster = event.kind == Kind::Raster || event.kind == Kind::Display;
    Stage expected = Stage::SceneRgb;
    Stage output_stage = Stage::SceneRgb;
    switch (event.kind) {
    case Kind::Raster:
    case Kind::Transfer:
    case Kind::Compute:
        expected = output_stage = event.carry;
        break;
    case Kind::Ui: output_stage = Stage::Ui; break;
    case Kind::Display: expected = Stage::Ui; output_stage = Stage::Display; break;
    case Kind::Prepare: expected = Stage::Display; output_stage = Stage::Prepare; break;
    case Kind::Swapchain: expected = Stage::Prepare; output_stage = Stage::Swapchain; break;
    case Kind::Present: expected = Stage::Swapchain; output_stage = Stage::Present; break;
    default: break;
    }
#ifdef BB_TEST_SHARED_POST_GRAPH
    Proof recipe = Proof::Known;
    if (scoped) {
        if (event.kind == Kind::Ui) expected = Stage::LdrComposite;
        if (event.kind == Kind::Merge && event.output.format != Format::Rgba16Float) {
            recipe = event.output.format == Format::Unknown ? Proof::Unknown : Proof::Failed;
            facts.Add(EffectiveRecipe, recipe);
        }
        if (event.kind == Kind::Raster) {
            recipe = event.recipe;
            const auto classified = [&] {
                switch (event.shader) {
                case 0xccbf44a6: return PostStep::Clamp;
                case 0x5e67d866: case 0xccb08339: case 0x5c02eaf8: return PostStep::Composite;
                case 0xed4c7668: return PostStep::Grade;
                case 0x8c08444c: return PostStep::Glow;
                default: return PostStep::Unknown;
                }
            }();
            if (classified != PostStep::Unknown && event.step != PostStep::Unknown && event.step != classified)
                recipe = Proof::Failed;
            switch (event.step) {
            case PostStep::Clamp: expected = Stage::SceneRgb; output_stage = Stage::HdrClamp; break;
            case PostStep::Composite: expected = Stage::HdrClamp; output_stage = Stage::LdrComposite; break;
            case PostStep::Grade: case PostStep::Glow:
                expected = output_stage = Stage::LdrComposite;
                break;
            case PostStep::Carry: break;
            case PostStep::Unknown: recipe = All(recipe, Proof::Unknown); break;
            }
            if (event.step != PostStep::Unknown && event.step != PostStep::Carry) {
                const auto format = event.step == PostStep::Clamp ? Format::Rgba16Float : Format::Rgba8Unorm;
                if (event.output.format != format)
                    recipe = All(recipe, event.output.format == Format::Unknown ? Proof::Unknown : Proof::Failed);
            }
            if (classified == PostStep::Unknown && event.step != PostStep::Carry)
                recipe = All(recipe, Proof::Unknown);
            facts.Add(EffectiveRecipe, recipe);
        } else if (event.kind == Kind::Transfer || event.kind == Kind::Compute) {
            recipe = event.step == PostStep::Carry ? event.recipe : Proof::Unknown;
            facts.Add(EffectiveRecipe, recipe);
        }
    }
#endif
    const bool guarded = event.kind == Kind::Merge || event.kind == Kind::Ui ||
                         event.kind == Kind::Display || event.kind == Kind::Prepare ||
                         event.kind == Kind::Swapchain || event.kind == Kind::Present;
    Proof boundary = guarded ? event.boundary : Proof::Known;
    if (event.kind == Kind::Merge) {
        for (std::size_t i = 0; i < index; ++i) {
            const auto& previous = entries_[i].event;
            if (previous.kind == Kind::Merge && previous.issued != Proof::Failed) {
                boundary = All(boundary, previous.issued == Proof::Known ?
                               Proof::Failed : Proof::Unknown);
            }
        }
    }
    if (guarded) {
        facts.Add(Boundary, boundary);
    }
#ifdef BB_TEST_SHARED_POST_GRAPH
    const Proof offered = All(event.issued, All(actual_order, All(recipe, missing ? Proof::Unknown : Proof::Known)));
    const Proof preserved_common = All(All(event.issued, event.pipeline),
        All(All(actual_order, destination), All(fresh, boundary)));
    auto base = Uniform(Proof::Failed);
    const auto probes = ActiveProbes();
    Coverage other_terms{};
    other_terms.fill(Proof::Known);
#else
    const Proof offered = event.issued;
    std::array<Lineage, ProbeCount> base{Lineage{Proof::Failed}, Lineage{Proof::Failed}};
    constexpr auto probes = ProbeCount;
#endif
    const Proof common = All(All(All(offered, event.pipeline), destination),
                             All(All(cached_format, cached_permutation), All(fresh, boundary)));

    auto prior = base;
    auto auxiliary = base;
    bool base_candidate = false, prior_candidate = false;
    bool duplicated_slot = false;
    bool contradictory_role = false;
    bool unknown_cached_role = false;
    std::uint32_t sampled = 0;
    for (std::size_t i = 0; i < inputs.size(); ++i) {
        const auto& input = inputs[i];
        entry.inputs[i] = input;
        for (std::size_t earlier = 0; earlier < i; ++earlier) {
            const auto& seen = entry.inputs[earlier];
            if (seen.stage == input.stage && seen.set == input.set &&
#ifdef BB_TEST_SHARED_POST_GRAPH
                (!scoped || seen.element == input.element) &&
#endif
                seen.binding == input.binding) {
                duplicated_slot = true;
            }
        }
        if (input.access == Proof::Known && input.image.Valid() &&
#ifdef BB_TEST_SHARED_POST_GRAPH
            (!scoped || (!input.element && input.sampler == Proof::Known)) &&
#endif
            input.stage == BindStage::Fragment && input.set == 0 && input.binding < 32) {
            sampled |= std::uint32_t{1} << input.binding;
        }
        auto writer_image = input.image;
        if (writer_image.Valid() && input.writer_view && input.access == Proof::Known) {
            writer_image.view = input.writer_view;
        }
        const auto read = input.writer_view && input.access == Proof::Unknown ?
                          ReadResult{{}, true} : ReadBefore(writer_image, index);
        facts.Add(Writer, read.writer);
        facts.Add(Alias, read.alias);
        facts.Add(InputAccess, input.access);
        const Role cached = cache && cached_permutation == Proof::Known ?
                            CachedRole(*cache, input) : input.role;
        const Proof semantics = cached == Role::Unknown || input.role == Role::Unknown ?
                                Proof::Unknown : cached == input.role ? Proof::Known : Proof::Failed;
        facts.Add(Semantic, semantics);
        contradictory_role |= semantics == Proof::Failed;
        unknown_cached_role |= cache && cached != Role::Other && semantics == Proof::Unknown;
        const bool is_prior = cached == Role::PriorDestination;
        const bool possible_base = cached == Role::BaseRgb || cached == Role::Unknown;
        base_candidate |= possible_base;
        prior_candidate |= is_prior;
        const bool same_present_image = has_output || input.image == event.output;
        const bool prior_matches = !is_prior ||
                                  (input.image.Valid() && input.image.Aliases(event.output) &&
                                   input.image.allocation == event.output.allocation &&
                                   input.image.uid == event.output.uid &&
                                   input.image.range == event.output.range);
        if (is_prior) {
            facts.Add(PriorFact, prior_matches ? Proof::Known : Proof::Failed);
        }

        for (std::size_t probe = 0; probe < probes; ++probe) {
            const auto& source = read.probes[probe];
            const bool prior_stage = source.stage == expected
#ifdef BB_TEST_SHARED_POST_GRAPH
                || (scoped && is_prior && event.untouched[probe] == Proof::Known)
#endif
                ;
            const Proof phase = source.proof == Proof::Known ?
                                (prior_stage ? Proof::Known : Proof::Failed) : source.proof;
            if (!same_present_image) {
                facts.Add(Boundary, Proof::Failed);
            }
            if (possible_base || is_prior) {
                facts.Add(StageFact, phase);
            }
            facts.Add(CoverageFact, input.read[probe]);
            const Proof external = input.external && !read.obstructed &&
                                   read.writer == Proof::Unknown ? Proof::Failed : phase;
            Proof joined = All(All(input.access, semantics), All(external, input.read[probe]));
#ifdef BB_TEST_SHARED_POST_GRAPH
            if (scoped) {
                const Proof contribution = is_prior && event.untouched[probe] == Proof::Known ?
                    Proof::Known : input.contribution[probe];
                facts.Add(Sampler, input.sampler);
                if (cached != Role::Other) facts.Add(Contribution, contribution);
                joined = All(joined, All(input.sampler, contribution));
                // A LUT (or an active glow term) needs its own real footprint even when it
                // carries no scene ancestry. An independently proved inactive bloom is fine.
                if (cached == Role::Lut || (cached == Role::AuxiliaryRgb && contribution != Proof::Failed)) {
                    other_terms[probe] = All(other_terms[probe],
                        All(All(input.access, input.sampler), All(input.read[probe], contribution)));
                }
            }
#endif
            const Proof proof = All(joined, prior_matches && same_present_image ? Proof::Known : Proof::Failed);
            auto& result = entry.input_lineage[i][probe];
            result = {proof, source.stage, source.base, source.auxiliary};
            if (!possible_base && !is_prior && cached != Role::AuxiliaryRgb) {
                continue;
            }
            auto& aggregate = is_prior ? prior[probe] : possible_base ? base[probe] : auxiliary[probe];
            aggregate.proof = Any(aggregate.proof, proof);
            if (proof == Proof::Known) {
#ifdef BB_TEST_SHARED_POST_GRAPH
                if (scoped) aggregate.stage = source.stage;
#endif
                aggregate.base |= source.base;
                aggregate.auxiliary |= source.auxiliary;
            }
        }
    }

    if (!base_candidate && !prior_candidate && event.kind != Kind::Merge &&
        event.kind != Kind::Clear && event.kind != Kind::Overwrite) {
        facts.Add(Semantic, inputs.empty() ? Proof::Unknown : Proof::Failed);
    }

    std::uint32_t required = 0;
    if (cache) {
        switch (cache->shader) {
        case 0xccbf44a6: required = 0b00001; break;
        case 0x5e67d866:
        case 0xccb08339: required = 0b11110; break;
        case 0xed4c7668: required = 0b00011; break;
        case 0x8c08444c: required = 0b01000; break;
        }
    }
#ifdef BB_TEST_SHARED_POST_GRAPH
    if (scoped) required |= event.required_slots;
#endif
    const Proof slots = duplicated_slot || contradictory_role ? Proof::Failed :
                        unknown_cached_role || (sampled & required) != required ? Proof::Unknown : Proof::Known;
    facts.Add(Semantic, slots);
#ifdef BB_TEST_SHARED_POST_GRAPH
    if (missing) facts.Add(InputAccess, Proof::Unknown);
#endif

    for (std::size_t probe = 0; probe < probes; ++probe) {
        Proof coverage = event.written[probe];
        facts.Add(CoverageFact, coverage);
        auto source = base[probe];
        if (event.kind == Kind::Merge) {
            // Adapter certifies the real merge and preserved upstream guards via pipeline.
            source = {Proof::Known};
        } else if ((event.kind == Kind::Clear || event.kind == Kind::Overwrite)
#ifdef BB_TEST_SHARED_POST_GRAPH
                   && (!scoped || event.untouched[probe] != Proof::Known)
#endif
        ) {
            source = {Proof::Failed};
        } else if (event.untouched[probe] == Proof::Known) {
            // A new whole-subresource version still needs the right prior contents.
            source = prior_candidate ? prior[probe] : Lineage{Proof::Unknown};
            facts.Add(PriorFact, source.proof);
            coverage = event.written[probe] == Proof::Known ? Proof::Failed : Proof::Known;
        } else if (raster && event.prior == Prior::Blend) {
            if (!prior_candidate) {
                prior[probe].proof = Proof::Unknown;
            }
            facts.Add(PriorFact, prior[probe].proof);
            source.proof = Any(source.proof, prior[probe].proof);
            source.base |= prior[probe].base;
            source.auxiliary |= prior[probe].auxiliary;
        } else if (inputs.empty() || (raster && event.prior == Prior::Unknown)) {
            source.proof = Proof::Unknown;
            if (raster && event.prior == Prior::Unknown) {
                facts.Add(PriorFact, Proof::Unknown);
            }
        }
        if (raster && event.prior == Prior::Blend && event.untouched[probe] != Proof::Known) {
            // Even a proved sampled path cannot certify if actual blend destination is unproved.
            source.proof = All(source.proof, prior[probe].proof);
        }

        auto& result = entry.result[probe];
        result.proof = All(All(common, coverage), All(slots, source.proof));
#ifdef BB_TEST_SHARED_POST_GRAPH
        if (scoped && event.untouched[probe] == Proof::Known && event.kind != Kind::Merge) {
            result.proof = All(All(preserved_common, coverage), source.proof);
        } else if (scoped) {
            result.proof = All(result.proof, other_terms[probe]);
        }
#endif
        result.stage = output_stage;
#ifdef BB_TEST_SHARED_POST_GRAPH
        if (scoped && event.untouched[probe] == Proof::Known) result.stage = source.stage;
#endif
        if (result.proof == Proof::Known) {
            result.base = source.base | event_bit;
            result.auxiliary = source.auxiliary | auxiliary[probe].base | auxiliary[probe].auxiliary;
        }
    }
#ifdef BB_TEST_SHARED_POST_GRAPH
    omitted_inputs_ += static_cast<std::uint32_t>(missing);
#endif
    return true;
}

inline ProbeLineage SceneTrace::PresentResult() const {
    if (Overflowed() || invalid_order_) {
        return {};
    }
    const Entry* present = nullptr;
    for (const auto& entry : Entries()) {
        if (entry.event.kind != Kind::Present) {
            continue;
        }
        if (present) {
            return {}; // This selection must name exactly one subsequent real app present.
        }
        present = &entry;
    }
    return present ? present->result : ProbeLineage{};
}

} // namespace BottleAncestry

