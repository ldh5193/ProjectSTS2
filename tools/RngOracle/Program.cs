// RngOracle - dumps deterministic test vectors from .NET 9 System.Random
// so the Python port (sim/rng.py) can be checked bit-exact against the same
// engine the game itself ships. The game uses System.Random under
// MegaCrit.Sts2.Core.Random.Rng (see notes/04_prng.md).
//
// Output is JSON on stdout. Run via:
//   dotnet run --project tools/RngOracle/RngOracle.csproj `
//     > tools/RngOracle/oracle.json
using System.Globalization;
using System.Text;
using System.Text.Json;

const int N_DOUBLE  = 32;
const int N_INT     = 16;
const int N_NAMED   = 16;

int[] seeds = new[] { 0, 1, 42, -1, int.MaxValue, int.MinValue, unchecked((int)0xDEADBEEF) };
int[] intMaxes = new[] { 2, 6, 13, 100, 1000 };
string[] categories = new[]
{
    "rewards", "shops", "transformations",
    "monster_ai", "combat_targets", "shuffle", "combat_card_generation",
    "combat_potion_generation", "unknown_map_point", "combat_energy_costs",
    "combat_card_selection", "combat_orb_generation", "treasure_room_relics",
    "niche", "up_front",
};

var output = new
{
    version = 1,
    framework = ".NET 9 System.Random",
    seeds = seeds,
    nextDouble = SampleDoubles(seeds, N_DOUBLE),
    nextInt = SampleInts(seeds, intMaxes, N_INT),
    nextBytes = SampleBytes(seeds, 32),
    deterministicHash = HashCategories(categories),
    seededRng = SampleSeededRng(seeds, categories, N_NAMED),
};

var opts = new JsonSerializerOptions
{
    WriteIndented = true,
    NumberHandling = System.Text.Json.Serialization.JsonNumberHandling.AllowNamedFloatingPointLiterals,
};
Console.OutputEncoding = Encoding.UTF8;
Console.WriteLine(JsonSerializer.Serialize(output, opts));

static Dictionary<string, double[]> SampleDoubles(int[] seeds, int n)
{
    var dict = new Dictionary<string, double[]>();
    foreach (var s in seeds)
    {
        var rng = new Random(s);
        var arr = new double[n];
        for (int i = 0; i < n; i++) arr[i] = rng.NextDouble();
        dict[s.ToString(CultureInfo.InvariantCulture)] = arr;
    }
    return dict;
}

static Dictionary<string, Dictionary<string, int[]>> SampleInts(int[] seeds, int[] maxes, int n)
{
    var dict = new Dictionary<string, Dictionary<string, int[]>>();
    foreach (var s in seeds)
    {
        var inner = new Dictionary<string, int[]>();
        foreach (var m in maxes)
        {
            var rng = new Random(s);
            var arr = new int[n];
            for (int i = 0; i < n; i++) arr[i] = rng.Next(m);
            inner[m.ToString(CultureInfo.InvariantCulture)] = arr;
        }
        dict[s.ToString(CultureInfo.InvariantCulture)] = inner;
    }
    return dict;
}

static Dictionary<string, int[]> SampleBytes(int[] seeds, int n)
{
    var dict = new Dictionary<string, int[]>();
    foreach (var s in seeds)
    {
        var rng = new Random(s);
        var buf = new byte[n];
        rng.NextBytes(buf);
        dict[s.ToString(CultureInfo.InvariantCulture)] = buf.Select(b => (int)b).ToArray();
    }
    return dict;
}

static Dictionary<string, int> HashCategories(string[] cats)
{
    var dict = new Dictionary<string, int>();
    foreach (var c in cats) dict[c] = GetDeterministicHashCode(c);
    return dict;
}

// Mirrors StringHelper.GetDeterministicHashCode (notes/04_prng.md §1).
static int GetDeterministicHashCode(string str)
{
    int num = 352654597;
    int num2 = num;
    for (int i = 0; i < str.Length; i += 2)
    {
        num = ((num << 5) + num) ^ str[i];
        if (i == str.Length - 1) break;
        num2 = ((num2 << 5) + num2) ^ str[i + 1];
    }
    return num + num2 * 1566083941;
}

static Dictionary<string, double[]> SampleSeededRng(int[] seeds, string[] cats, int n)
{
    // Mirrors MegaCrit.Sts2.Core.Random.Rng(uint seed, string name):
    //   seed' = (seed + GetDeterministicHashCode(name))   [unchecked uint arithmetic]
    //   _random = new System.Random((int) seed');
    var dict = new Dictionary<string, double[]>();
    foreach (var s in seeds)
    {
        foreach (var cat in cats)
        {
            uint combined = unchecked((uint)s + (uint)GetDeterministicHashCode(cat));
            var rng = new Random(unchecked((int)combined));
            var arr = new double[n];
            for (int i = 0; i < n; i++) arr[i] = rng.NextDouble();
            dict[$"{s}:{cat}"] = arr;
        }
    }
    return dict;
}
