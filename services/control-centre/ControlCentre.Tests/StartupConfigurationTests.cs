// SPDX-License-Identifier: AGPL-3.0-only
using ControlCentre.Platform;
using Microsoft.AspNetCore.Hosting.Server.Features;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Npgsql;
using Xunit;

namespace ControlCentre.Tests;

public sealed class StartupConfigurationTests
{
  [Theory]
  [InlineData("8080")]
  [InlineData("18081")]
  public void HttpPortComesFromAspNetCoreEnvironment(string port)
  {
    WithEnvironment(new Dictionary<string, string?> { ["ASPNETCORE_HTTP_PORTS"] = port, ["ASPNETCORE_URLS"] = null, ["URLS"] = null, ["HTTP_PORTS"] = null }, () =>
    {
      using var host = new Host();
      using var client = host.CreateClient();
      var configuration = host.Services.GetRequiredService<IConfiguration>();
      Assert.Equal(port, configuration["HTTP_PORTS"]);
      Assert.Contains("http://*:" + port, host.Server.Features.Get<IServerAddressesFeature>()!.Addresses);
      Assert.True(string.IsNullOrEmpty(configuration["URLS"]));
    });
  }
  [Fact]
  public void ExplicitListeningAddressComesFromAspNetCoreEnvironment()
  {
    WithEnvironment(new Dictionary<string, string?> { ["ASPNETCORE_HTTP_PORTS"] = "8080", ["ASPNETCORE_URLS"] = "http://0.0.0.0:18081", ["URLS"] = null }, () =>
    {
      using var host = new Host();
      using var client = host.CreateClient();
      Assert.Equal("http://0.0.0.0:18081", host.Services.GetRequiredService<IConfiguration>()["URLS"]);
      Assert.Contains("http://0.0.0.0:18081", host.Server.Features.Get<IServerAddressesFeature>()!.Addresses);
    });
  }
  [Theory]
  [InlineData("CC_DB_CONNECTION", false)]
  [InlineData("CC_DB_MIGRATE_CONNECTION", true)]
  public void RuntimeAndMigrationConnectionsDisableGss(string variable, bool migration)
  {
    using var host = new Host();
    WithEnvironment(new Dictionary<string, string?> { [variable] = "Host=127.0.0.1;Database=controlcentre_test;GSS Encryption Mode=Require" }, () =>
    {
      if (migration)
      {
        using var db = new DesignTimeFactory().CreateDbContext([]);
        AssertGssDisabled(db);
      }
      else
      {
        using var client = host.CreateClient();
        using var scope = host.Services.CreateScope();
        AssertGssDisabled(scope.ServiceProvider.GetRequiredService<CentreDb>());
      }
    });
  }
  private static void AssertGssDisabled(CentreDb db)
  {
    var connection = new NpgsqlConnectionStringBuilder(db.Database.GetDbConnection().ConnectionString);
    Assert.Equal(GssEncryptionMode.Disable, connection.GssEncryptionMode);
    Assert.Equal("controlcentre_test", connection.Database);
  }
  private static void WithEnvironment(Dictionary<string, string?> values, Action test)
  {
    var previous = values.Keys.ToDictionary(key => key, Environment.GetEnvironmentVariable);
    try
    {
      foreach (var (key, value) in values) Environment.SetEnvironmentVariable(key, value);
      test();
    }
    finally
    {
      foreach (var (key, value) in previous) Environment.SetEnvironmentVariable(key, value);
    }
  }
}
