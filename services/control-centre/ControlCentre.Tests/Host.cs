// SPDX-License-Identifier: AGPL-3.0-only
using System.IdentityModel.Tokens.Jwt;
using System.Net.Http.Headers;
using System.Security.Claims;
using System.Security.Cryptography;
using ControlCentre.Platform;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Microsoft.IdentityModel.Protocols.OpenIdConnect;
using Microsoft.IdentityModel.Tokens;
using Xunit;

[assembly: Xunit.v3.Parallelization(Mode = Xunit.Sdk.ParallelMode.None)]
namespace ControlCentre.Tests;

public static class TestSettings
{
  public static readonly string FilePath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".config/ooh/control-centre-test.env");
  public static bool Available => File.Exists(FilePath);
  public static Dictionary<string, string> Load()
  {
    var values = File.ReadAllLines(FilePath).Where(x => !string.IsNullOrWhiteSpace(x) && !x.StartsWith('#'))
        .Select(x => x.StartsWith("export ", StringComparison.Ordinal) ? x[7..] : x)
        .Select(x => x.Split('=', 2)).Where(x => x.Length == 2)
        .ToDictionary(x => x[0], x => x[1].Trim().Trim('\'', '"'));
    foreach (var name in new[] { "CC_TEST_DB_CONNECTION", "CC_TEST_DB_MIGRATE_CONNECTION" })
    {
      var parsed = new Npgsql.NpgsqlConnectionStringBuilder(values[name]);
      if (parsed.Database != "controlcentre_test" || parsed.Username != (name == "CC_TEST_DB_CONNECTION" ? "controlcentre_test_app" : "controlcentre_test"))
        throw new InvalidOperationException("Tests require the isolated test database and roles");
    }
    return values;
  }
}
public sealed class DatabaseFactAttribute : FactAttribute
{
  public DatabaseFactAttribute([System.Runtime.CompilerServices.CallerFilePath] string? sourceFilePath = null, [System.Runtime.CompilerServices.CallerLineNumber] int sourceLineNumber = -1) : base(sourceFilePath, sourceLineNumber) { if (!TestSettings.Available) Skip = "Waiting for the test database settings file from install/59-control-centre-databases.sh"; }
}
public sealed class FakeKafka : IKafka
{
  public List<(string Topic, string Key, string Value)> Published { get; } = [];
  public bool Fail { get; set; }
  public Task Publish(string topic, string key, string value, CancellationToken ct)
  {
    if (Fail) throw new IOException("Synthetic publish failure");
    Published.Add((topic, key, value)); return Task.CompletedTask;
  }
  public KafkaRecord? Read(CancellationToken ct) => null;
  public void Commit(KafkaRecord record) { }
}
public sealed class FakeDelay : IRetryDelay
{
  public List<TimeSpan> Waits { get; } = [];
  public Task Wait(TimeSpan duration, CancellationToken ct) { Waits.Add(duration); return Task.CompletedTask; }
}
public sealed class Host : WebApplicationFactory<Program>
{
  private readonly SymmetricSecurityKey key = new(RandomNumberGenerator.GetBytes(64));
  public FakeKafka Kafka { get; } = new();
  public TestLogs Logs { get; } = new();
  public Host(bool database = false)
  {
    Environment.SetEnvironmentVariable("CC_KEY_ENCRYPTION_KEY", Convert.ToBase64String(new byte[32]));
    Environment.SetEnvironmentVariable("CC_DB_CONNECTION", database ? TestSettings.Load()["CC_TEST_DB_CONNECTION"] : "Host=127.0.0.1;Port=1;Database=controlcentre_test;Timeout=1");
    Environment.SetEnvironmentVariable("CC_OIDC_ISSUER", "https://issuer.invalid");
    Environment.SetEnvironmentVariable("CC_OIDC_AUDIENCE", "ooh-control-centre");
  }
  protected override void ConfigureWebHost(IWebHostBuilder builder)
  {
    builder.ConfigureLogging(logging => { logging.ClearProviders(); logging.AddProvider(Logs); });
    builder.ConfigureServices(services =>
    {
      foreach (var descriptor in services.Where(x => x.ServiceType == typeof(IHostedService) && x.ImplementationType == typeof(KafkaWorker)).ToArray()) services.Remove(descriptor);
      services.AddTransient<IStartupFilter, TestPort>();
      services.RemoveAll<IKafka>(); services.AddSingleton<IKafka>(Kafka);
      services.PostConfigure<JwtBearerOptions>(JwtBearerDefaults.AuthenticationScheme, o =>
          {
            o.Authority = null; o.MetadataAddress = "";
            o.Configuration = new OpenIdConnectConfiguration { Issuer = "https://issuer.invalid" };
            o.TokenValidationParameters = new TokenValidationParameters
            {
              ValidateIssuer = true,
              ValidIssuer = "https://issuer.invalid",
              ValidateAudience = true,
              ValidAudience = "ooh-control-centre",
              ValidateLifetime = true,
              ValidateIssuerSigningKey = true,
              IssuerSigningKey = key,
              ClockSkew = TimeSpan.Zero
            };
          });
    });
  }
  public HttpClient Client(string role = "admin", string? subject = null, string audience = "ooh-control-centre", bool expired = false, bool wrongSignature = false, string email = "synthetic-user@test.invalid", string name = "Synthetic User", int port = 8080)
  {
    var client = CreateClient();
    client.BaseAddress = new Uri($"http://localhost:{port}");
    var claims = new List<Claim> { new("sub", subject ?? "test-" + Guid.NewGuid()), new("azp", role switch { "harness" => "ooh-harness-api", "gateway" => "ooh-model-gateway", "self" => "ooh-admin-console", _ => "ooh-control-centre" }) };
    if (role == "self")
    {
      claims.Add(new Claim("email", email));
      claims.Add(new Claim("name", name));
    }
    if (role == "admin") claims.Add(new Claim("realm_access", "{\"roles\":[\"ooh-admin\"]}", JsonClaimValueTypes.Json));
    var token = new JwtSecurityToken("https://issuer.invalid", audience, claims,
        DateTime.UtcNow.AddMinutes(-10), expired ? DateTime.UtcNow.AddMinutes(-5) : DateTime.UtcNow.AddMinutes(5), new SigningCredentials(wrongSignature ? new SymmetricSecurityKey(RandomNumberGenerator.GetBytes(64)) : key, SecurityAlgorithms.HmacSha256));
    client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", new JwtSecurityTokenHandler().WriteToken(token));
    return client;
  }
}

public sealed class TestPort : IStartupFilter
{
  public Action<Microsoft.AspNetCore.Builder.IApplicationBuilder> Configure(Action<Microsoft.AspNetCore.Builder.IApplicationBuilder> next) => app =>
  {
    app.Use(nextHandler => context => { context.Connection.LocalPort = context.Request.Host.Port ?? 8080; return nextHandler(context); });
    next(app);
  };
}

public sealed class TestLogs : ILoggerProvider
{
  public System.Collections.Concurrent.ConcurrentBag<string> Entries { get; } = [];
  public ILogger CreateLogger(string categoryName) => new CapturedLogger(Entries);
  public void Dispose() { }
  private sealed class CapturedLogger(System.Collections.Concurrent.ConcurrentBag<string> entries) : ILogger
  {
    public IDisposable? BeginScope<TState>(TState state) where TState : notnull => null;
    public bool IsEnabled(LogLevel logLevel) => true;
    public void Log<TState>(LogLevel logLevel, EventId eventId, TState state, Exception? exception, Func<TState, Exception?, string> formatter) => entries.Add(formatter(state, exception));
  }
}
