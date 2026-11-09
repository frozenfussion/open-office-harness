// SPDX-License-Identifier: AGPL-3.0-only
using System.Text.Json;
using System.Text.Json.Nodes;
using Json.Schema;

namespace ControlCentre.Platform;

public sealed class SchemaChecks
{
  private readonly JsonSchema manifest;
  private readonly JsonSchema envelope;
  public SchemaChecks()
  {
    var documents = new Dictionary<string, JsonNode>();
    var assembly = typeof(SchemaChecks).Assembly;
    foreach (var resource in assembly.GetManifestResourceNames().Where(x => x.Contains(".Schemas.", StringComparison.Ordinal)))
    {
      using var stream = assembly.GetManifestResourceStream(resource)!;
      using var reader = new StreamReader(stream);
      var name = resource[(resource.IndexOf(".Schemas.", StringComparison.Ordinal) + 9)..];
      documents[name] = JsonNode.Parse(reader.ReadToEnd())!;
    }
    manifest = JsonSchema.FromText(documents["manifest.schema.json"].ToJsonString());
    // Bundle local references so neither validation nor startup fetches schemas from a network.
    envelope = JsonSchema.FromText(Expand(documents["envelope.schema.json"], documents).ToJsonString());
  }
  private static JsonNode Expand(JsonNode node, Dictionary<string, JsonNode> documents)
  {
    if (node is JsonObject obj)
    {
      if (obj["$ref"] is JsonValue reference)
        return Expand(documents[Path.GetFileName(reference.GetValue<string>())], documents);
      return new JsonObject(obj.Select(x => KeyValuePair.Create(x.Key, x.Value is null ? null : Expand(x.Value, documents))));
    }
    if (node is JsonArray array) return new JsonArray(array.Select(x => x is null ? null : Expand(x, documents)).ToArray());
    return node.DeepClone();
  }
  public bool Manifest(JsonNode? value) => manifest.Evaluate(JsonSerializer.SerializeToElement(value), new EvaluationOptions { RequireFormatValidation = true }).IsValid;
  public bool Envelope(JsonNode? value) => value is JsonObject obj && obj["type"]?.ToString() == "approval.requested" &&
      envelope.Evaluate(JsonSerializer.SerializeToElement(value), new EvaluationOptions { RequireFormatValidation = true }).IsValid;
}
