// SPDX-License-Identifier: AGPL-3.0-only
using System.Text.RegularExpressions;
using Npgsql;

namespace ControlCentre.Platform;

public static class Diagnostics
{
  public static void Failure(ILogger logger, string operation, Exception error, IEnumerable<string>? sensitive = null)
  {
    var cause = error.GetBaseException();
    var message = cause is PostgresException postgres ? postgres.MessageText : cause.Message;
    var secrets = new List<string>(sensitive ?? []);
    foreach (var setting in new[] { "CC_DB_CONNECTION", "CC_DB_MIGRATE_CONNECTION", "CC_KAFKA_PASSWORD", "CC_KEY_ENCRYPTION_KEY" })
    {
      var value = Environment.GetEnvironmentVariable(setting);
      if (string.IsNullOrEmpty(value)) continue;
      secrets.Add(value);
      if (setting.Contains("DB_", StringComparison.Ordinal))
      {
        try { secrets.Add(new NpgsqlConnectionStringBuilder(value).Password ?? ""); }
        catch (ArgumentException) { }
      }
    }
    foreach (var secret in secrets.Where(x => !string.IsNullOrEmpty(x)).OrderByDescending(x => x.Length))
      message = message.Replace(secret, "[redacted]", StringComparison.Ordinal);
    message = Regex.Replace(message, "[\\\"]([^\\\"]*)[\\\"]|'[^']*'", "[redacted]");
    message = Regex.Replace(message, @"[\w.+-]+@[\w.-]+|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[redacted]");
    logger.LogWarning("{Operation}: {ExceptionType}: {ExceptionMessage}", operation, cause.GetType().FullName, message);
  }
}
