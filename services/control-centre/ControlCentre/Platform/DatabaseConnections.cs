// SPDX-License-Identifier: AGPL-3.0-only
using Npgsql;

namespace ControlCentre.Platform;

public static class DatabaseConnections
{
  public static string Configure(string connection) => new NpgsqlConnectionStringBuilder(connection)
  {
    // The chiseled runtime has no Kerberos library; these connections use password authentication.
    GssEncryptionMode = GssEncryptionMode.Disable
  }.ConnectionString;
}
