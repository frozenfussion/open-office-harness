// SPDX-License-Identifier: AGPL-3.0-only
using System.Text.Json;
using ControlCentre.Platform;
using ControlCentre.Access;
using ControlCentre.Rights;
using ControlCentre.Registry;
using ControlCentre.Approvals;
using ControlCentre.Audit;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.AspNetCore.DataProtection;
using Microsoft.EntityFrameworkCore;
using Npgsql;

var builder = WebApplication.CreateBuilder(args);
builder.Configuration.Sources.Clear();
// Kestrel reads HTTP_PORTS/URLS after the ASPNETCORE_ prefix is removed.
builder.Configuration.AddEnvironmentVariables("ASPNETCORE_");
builder.Configuration.AddEnvironmentVariables();
builder.Logging.ClearProviders();
builder.Logging.AddJsonConsole();
// Framework request logging includes paths, which can contain a person's identifier.
builder.Logging.AddFilter("Microsoft.AspNetCore", LogLevel.Warning);
builder.Logging.AddFilter("Microsoft.AspNetCore.Authentication", LogLevel.Information);
builder.Logging.AddFilter("Microsoft.EntityFrameworkCore", LogLevel.None);
string Required(string name) => Environment.GetEnvironmentVariable(name) is { Length: > 0 } value ? value : throw new InvalidOperationException($"Missing environment variable {name}");
var migrate = args.Contains("migrate");
builder.Services.AddDbContext<CentreDb>(o => o.UseNpgsql(DatabaseConnections.Configure(Required(migrate ? "CC_DB_MIGRATE_CONNECTION" : "CC_DB_CONNECTION"))));
if (migrate)
{
  using var migrationApp = builder.Build();
  using var scope = migrationApp.Services.CreateScope();
  await scope.ServiceProvider.GetRequiredService<CentreDb>().Database.MigrateAsync();
  return;
}
try { builder.Services.AddSingleton(new ModelKeys(Environment.GetEnvironmentVariable("CC_KEY_ENCRYPTION_KEY"))); }
catch (InvalidOperationException)
{
  Console.WriteLine(JsonSerializer.Serialize(new { level = "error", message = "CC_KEY_ENCRYPTION_KEY must contain 32 bytes encoded as base64" }));
  Environment.ExitCode = 1;
  return;
}
if (string.IsNullOrEmpty(builder.Configuration["HTTP_PORTS"]) && string.IsNullOrEmpty(builder.Configuration["URLS"]))
  builder.Configuration["HTTP_PORTS"] = "8080;8081";
builder.Services.ConfigureHttpJsonOptions(o =>
{
  o.SerializerOptions.PropertyNamingPolicy = Api.Json.PropertyNamingPolicy;
  o.SerializerOptions.DefaultIgnoreCondition = Api.Json.DefaultIgnoreCondition;
});
builder.Services.AddAuthentication(JwtBearerDefaults.AuthenticationScheme).AddJwtBearer(o =>
{
  o.Authority = Required("CC_OIDC_ISSUER");
  o.Audience = Required("CC_OIDC_AUDIENCE");
  o.MapInboundClaims = false;
  o.IncludeErrorDetails = false;
  o.TokenValidationParameters.ClockSkew = TimeSpan.Zero;
  o.Events = new JwtBearerEvents
  {
    OnTokenValidated = c =>
    {
      if (string.IsNullOrWhiteSpace(c.Principal?.FindFirst("sub")?.Value)) c.Fail("Subject required");
      return Task.CompletedTask;
    },
    OnChallenge = async c => { c.HandleResponse(); c.Response.StatusCode = 401; await c.Response.WriteAsJsonAsync(new { code = "unauthorized", message = "Valid token required" }); },
    OnForbidden = async c => { c.Response.StatusCode = 403; await c.Response.WriteAsJsonAsync(new { code = "forbidden", message = "Operation not allowed" }); }
  };
});
builder.Services.AddAuthorization();
Tracing.Register(builder.Services, builder.Configuration);
builder.Services.AddDataProtection().UseEphemeralDataProtectionProvider();
builder.Services.AddSingleton<SchemaChecks>();
builder.Services.AddSingleton(TimeProvider.System);
builder.Services.AddSingleton(new DisplayCalendar(builder.Configuration["CC_DISPLAY_TIME_ZONE"] ?? "Asia/Kuala_Lumpur"));
builder.Services.AddSingleton(_ => new HttpClient(new SocketsHttpHandler { PooledConnectionLifetime = TimeSpan.FromMinutes(5) }) { Timeout = Timeout.InfiniteTimeSpan });
builder.Services.AddSingleton<ModelConnection>();
builder.Services.AddSingleton<IKafka, KafkaClient>();
builder.Services.AddSingleton<IRetryDelay, RetryDelay>();
builder.Services.AddScoped<DeadLetterConsumer>();
builder.Services.AddSingleton<OperationsClient>();
builder.Services.AddSingleton<TraceClient>();
builder.Services.AddSingleton<ServiceHealth>();
builder.Services.AddHostedService<HealthPoller>();
builder.Services.AddScoped<ApprovalConsumer>();
builder.Services.AddScoped<OutboxPublisher>();
builder.Services.AddHostedService<KafkaWorker>();
var app = builder.Build();
app.Use(async (c, next) =>
{
  if (c.Request.Path.StartsWithSegments("/api/admin")) c.Response.Headers["X-Display-Time-Zone"] = c.RequestServices.GetRequiredService<DisplayCalendar>().Zone.Id;
  try { await next(c); }
  catch (ApiException e) { await Api.Error(e.Status, e.Code, e.Message).ExecuteAsync(c); }
  catch (Exception e) when (e is JsonException or BadHttpRequestException)
  { await Api.Error(400, "invalid_input", "Invalid input").ExecuteAsync(c); }
  catch (DbUpdateConcurrencyException) { await Api.Error(409, "conflict", "Entry changed; read it again").ExecuteAsync(c); }
  catch (DbUpdateException e) when (e.InnerException is PostgresException { SqlState: "23505" })
  { await Api.Error(409, "conflict", "An active entry already exists").ExecuteAsync(c); }
  catch (Exception error)
  {
    System.Diagnostics.Activity.Current?.SetStatus(System.Diagnostics.ActivityStatusCode.Error);
    Diagnostics.Failure(app.Logger, "Request could not be completed", error, c.User.Claims.Select(x => x.Value).Append(c.Request.Headers.Authorization.ToString()).Append(c.Request.Headers.Authorization.ToString().Replace("Bearer ", "", StringComparison.OrdinalIgnoreCase)));
    await Api.Error(503, "unavailable", "Control Centre unavailable").ExecuteAsync(c);
  }
});
app.Use(async (c, next) =>
{
  if ((c.Request.Path == "/api/models" || c.Request.Path.StartsWithSegments("/api/models")) && c.Connection.LocalPort != 8081)
  { await Api.Error(404, "not_found", "Route not found").ExecuteAsync(c); return; }
  await next(c);
});
app.UseAuthentication();
app.UseAuthorization();
app.Use(async (c, next) =>
{
  if (c.User.Identity?.IsAuthenticated == true && c.User.FindFirst("azp")?.Value is not ("ooh-harness-api" or "ooh-model-gateway" or "ooh-control-centre"))
  {
    var db = c.RequestServices.GetRequiredService<CentreDb>();
    await People.Observe(c, db, c.RequestServices.GetRequiredService<DisplayCalendar>(), c.RequestServices.GetRequiredService<TimeProvider>());
  }
  await next(c);
});
app.MapGet("/health", async (HttpContext c, CentreDb db) =>
{
  Api.Query(c);
  return await db.Database.CanConnectAsync() ? Results.Ok(new { status = "ok" }) : Api.Error(503, "unavailable", "Database unavailable");
});
SkillRequestRoutes.Map(app);
OperationsRoutes.Map(app);
TraceRoutes.Map(app);
ReplayRoutes.Map(app);
TierRequestRoutes.Map(app);
AccessRoutes.Map(app);
RightsRoutes.Map(app);
RegistryRoutes.Map(app);
ApprovalRoutes.Map(app);
AuditRoutes.Map(app);
app.MapFallback(() => Api.Error(404, "not_found", "Route not found")).RequireAuthorization();
app.Run();

public partial class Program;
