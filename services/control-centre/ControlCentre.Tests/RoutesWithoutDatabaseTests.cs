// SPDX-License-Identifier: AGPL-3.0-only
using System.Net;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json.Nodes;
using ControlCentre.Platform;
using Xunit;

namespace ControlCentre.Tests;

public sealed class RoutesWithoutDatabaseTests
{
  public static TheoryData<string, string> Routes => new()
    {
        { "POST", "/api/access/observe" }, { "GET", "/api/admin/access-requests" }, { "GET", "/api/admin/access-requests/count?status=pending" }, { "POST", "/api/admin/access-requests/bad/approve" }, { "POST", "/api/admin/access-requests/bad/reject" }, { "POST", "/api/admin/access-requests/bad/revoke" }, { "POST", "/api/rights/check" }, { "GET", "/api/rights/me?user_id=test" }, { "GET", "/api/skills?user_id=test" },
        { "GET", "/api/models?purpose=classification" }, { "GET", "/api/admin/people" }, { "GET", "/api/admin/people/test" },
        { "GET", "/api/admin/grants" }, { "GET", "/api/models/bad/key" }, { "GET", "/api/admin/rights" }, { "POST", "/api/admin/grants" }, { "DELETE", "/api/admin/grants/bad" },
        { "GET", "/api/admin/models" }, { "POST", "/api/admin/models/bad/test" }, { "POST", "/api/admin/models" }, { "GET", "/api/admin/models/bad" }, { "PUT", "/api/admin/models/bad" }, { "DELETE", "/api/admin/models/bad" },
        { "GET", "/api/admin/skills" }, { "POST", "/api/admin/skills" }, { "GET", "/api/admin/skills/slides" }, { "PUT", "/api/admin/skills/slides" }, { "DELETE", "/api/admin/skills/slides" },
        { "GET", "/api/admin/approvals" }, { "GET", "/api/admin/approvals/bad" }, { "POST", "/api/admin/approvals/bad/decision" }, { "GET", "/api/admin/audit" }
    };
  [Theory, MemberData(nameof(Routes))]
  public async Task EveryRouteRequiresValidAudienceAndSignature(string method, string path)
  {
    using var host = new Host();
    using var anonymous = host.CreateClient();
    using var wrongAudience = host.Client(audience: "other-api");
    using var expired = host.Client(expired: true);
    using var wrongSignature = host.Client(wrongSignature: true);
    foreach (var client in new[] { anonymous, wrongAudience, expired, wrongSignature })
    {
      var response = await Send(client, method, path);
      Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
      Assert.Equal("unauthorized", (await response.Content.ReadFromJsonAsync<JsonObject>(TestContext.Current.CancellationToken))!["code"]!.GetValue<string>());
    }
  }
  [Theory, MemberData(nameof(Routes))]
  public async Task EveryRouteRefusesUnauthorizedPrincipal(string method, string path)
  {
    using var host = new Host();
    using var client = host.Client("other");
    var response = await Send(client, method, path, "{\"user_id\":\"someone-else\",\"action\":\"image.generate\",\"target\":\"ignored\"}");
    Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
  }
  [Theory, MemberData(nameof(Routes))]
  public async Task EveryRouteRejectsUnknownInput(string method, string path)
  {
    using var host = new Host();
    using var client = host.Client(path == "/api/access/observe" ? "harness" : path.StartsWith("/api/models", StringComparison.Ordinal) ? "gateway" : "admin");
    var response = await Send(client, method, path + (path.Contains('?') ? "&" : "?") + "unknown=x");
    Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
  }
  [Fact]
  public async Task HealthFailsWhenDatabaseIsUnavailableAndRejectsInput()
  {
    using var host = new Host(); using var client = host.CreateClient();
    Assert.Equal(HttpStatusCode.ServiceUnavailable, (await client.GetAsync("/health", TestContext.Current.CancellationToken)).StatusCode);
    Assert.Equal(HttpStatusCode.BadRequest, (await client.GetAsync("/health?extra=1", TestContext.Current.CancellationToken)).StatusCode);
  }
  [Theory]
  [InlineData("{\"user_id\":\"u\",\"action\":\"chat.tier\",\"target\":\"0\"}")]
  [InlineData("{\"user_id\":\"u\",\"action\":\"chat.tier\",\"target\":\"-1\"}")]
  [InlineData("{\"user_id\":\"u\",\"action\":\"other\",\"target\":\"x\"}")]
  [InlineData("{\"user_id\":\"u\",\"action\":\"image.generate\",\"target\":\"x\",\"extra\":true}")]
  [InlineData("{\"user_id\":\"u\",\"user_id\":\"u\",\"action\":\"image.generate\",\"target\":\"x\"}")]
  [InlineData("{}")]
  [InlineData("null")]
  [InlineData("{\"user_id\":4,\"action\":\"image.generate\",\"target\":\"ignored\"}")]
  [InlineData("{\"user_id\":\"u\",\"action\":\"image.generate\",\"target\":null}")]
  public async Task RightsInputFailsBeforeDatabase(string body)
  {
    using var host = new Host(); using var client = host.Client("harness");
    Assert.Equal(HttpStatusCode.BadRequest, (await Send(client, "POST", "/api/rights/check", body)).StatusCode);
  }
  [Theory]
  [InlineData("/api/models?purpose=chat")]
  [InlineData("/api/models?purpose=image&tier=1")]
  [InlineData("/api/models?purpose=chat&tier=0")]
  [InlineData("/api/admin/approvals?limit=201")]
  [InlineData("/api/admin/approvals?before=bad")]
  [InlineData("/api/admin/audit?before_id=0")]
  [InlineData("/api/admin/rights?limit=0")]
  public async Task InvalidQueries(string path)
  {
    using var host = new Host(); using var client = host.Client(path == "/api/access/observe" ? "harness" : path.StartsWith("/api/models", StringComparison.Ordinal) ? "gateway" : "admin");
    Assert.Equal(HttpStatusCode.BadRequest, (await client.GetAsync(path.StartsWith("/api/models", StringComparison.Ordinal) ? "http://localhost:8081" + path : path, TestContext.Current.CancellationToken)).StatusCode);
  }
  [Fact]
  public async Task InternalRightsFailureReturnsUnavailable()
  {
    using var host = new Host(); using var client = host.Client("harness");
    var response = await Send(client, "POST", "/api/rights/check", "{\"user_id\":\"u\",\"action\":\"image.generate\",\"target\":\"ignored\"}");
    Assert.Equal(HttpStatusCode.ServiceUnavailable, response.StatusCode);
  }
  [Fact]
  public void AdminTokenUsesKeycloakObjectClaim()
  {
    using var host = new Host(); using var client = host.Client();
    var token = new System.IdentityModel.Tokens.Jwt.JwtSecurityTokenHandler().ReadJwtToken(client.DefaultRequestHeaders.Authorization!.Parameter);
    using var payload = System.Text.Json.JsonDocument.Parse(token.Payload.SerializeToJson());
    var realm = payload.RootElement.GetProperty("realm_access");
    Assert.Equal(System.Text.Json.JsonValueKind.Object, realm.ValueKind);
    Assert.Equal("ooh-admin", realm.GetProperty("roles")[0].GetString());
  }
  [Fact]
  public void BundledSchemasMatchContracts()
  {
    var folder = new DirectoryInfo(AppContext.BaseDirectory);
    while (folder is not null && !Directory.Exists(Path.Combine(folder.FullName, "contracts"))) folder = folder.Parent;
    Assert.NotNull(folder);
    var bundled = Path.Combine(folder.FullName, "services/control-centre/ControlCentre/Platform/Schemas");
    foreach (var path in Directory.GetFiles(bundled, "*.json"))
    {
      var name = Path.GetFileName(path);
      var contract = name == "manifest.schema.json" ? "skills/" + name :
          name == "envelope.schema.json" ? "events/" + name : "events/payloads/" + name;
      Assert.Equal(File.ReadAllText(Path.Combine(folder.FullName, "contracts", contract)), File.ReadAllText(path));
    }
  }
  [Fact]
  public void ManifestAndEnvelopeValidation()
  {
    var schemas = new SchemaChecks();
    var manifest = ValidManifest("schema-test");
    Assert.True(schemas.Manifest(manifest));
    manifest["extra"] = true; Assert.False(schemas.Manifest(manifest)); manifest.Remove("extra");
    manifest.Remove("topic"); Assert.False(schemas.Manifest(manifest));
    var envelope = Envelope(); Assert.True(schemas.Envelope(envelope));
    envelope["event_id"] = "bad"; Assert.False(schemas.Envelope(envelope));
    envelope = Envelope(); envelope["payload"]!["extra"] = true; Assert.False(schemas.Envelope(envelope));
  }
  public static JsonObject ValidManifest(string name) => new()
  {
    ["name"] = name,
    ["title"] = "Test skill",
    ["kind"] = "service",
    ["description"] = "Synthetic skill",
    ["input_schema"] = "input.schema.json",
    ["output_schema"] = "output.schema.json",
    ["right"] = "skill." + name,
    ["needs_approval"] = false,
    ["version"] = "1.0.0",
    ["topic"] = "skill.requests.slides"
  };
  public static JsonObject Envelope() => new()
  {
    ["event_id"] = Guid.NewGuid().ToString(),
    ["type"] = "approval.requested",
    ["version"] = 1,
    ["occurred_at"] = DateTime.UtcNow.ToString("O"),
    ["correlation_id"] = Guid.NewGuid().ToString(),
    ["user_id"] = "synthetic-requester",
    ["producer"] = "test",
    ["payload"] = new JsonObject
    { ["action"] = "stage.check", ["details"] = new JsonObject(), ["risk"] = "low", ["requested_by"] = "synthetic-requester" }
  };
  public static Task<HttpResponseMessage> Send(HttpClient client, string method, string path, string body = "{}") =>
      client.SendAsync(new HttpRequestMessage(new HttpMethod(method), path.StartsWith("/api/models", StringComparison.Ordinal) ? "http://localhost:8081" + path : path) { Content = new StringContent(body, Encoding.UTF8, "application/json") });
}
