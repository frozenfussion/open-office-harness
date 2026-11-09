// SPDX-License-Identifier: AGPL-3.0-only
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Design;

namespace ControlCentre.Platform;

public sealed class DesignTimeFactory : IDesignTimeDbContextFactory<CentreDb>
{
  public CentreDb CreateDbContext(string[] args)
  {
    var connection = Environment.GetEnvironmentVariable("CC_DB_MIGRATE_CONNECTION") ?? throw new InvalidOperationException("Set CC_DB_MIGRATE_CONNECTION for migration tooling");
    return new CentreDb(new DbContextOptionsBuilder<CentreDb>().UseNpgsql(DatabaseConnections.Configure(connection)).Options);
  }
}
