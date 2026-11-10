// SPDX-License-Identifier: AGPL-3.0-only
using System.Globalization;
using ControlCentre.Platform;
using Microsoft.EntityFrameworkCore;

namespace ControlCentre.Registry;

public sealed record MainChoice(int Tier, string Title, bool ThinkingSwitch);
public sealed record RequestableTier(int Tier, string Title, string? Requested);
public static class TierChoices
{
  public static async Task<List<MainChoice>> MainEntries(CentreDb db)
  {
    var rows = await db.Models.Where(x => x.DeletedAt == null && x.Purpose == "chat" && x.Role == "main" && x.Tier != null)
      .OrderBy(x => x.Priority).ThenBy(x => x.CreatedAt).ThenBy(x => x.Id)
      .Select(x => new MainChoice(x.Tier!.Value, x.Title, x.RequestSettingsThinkingOff != null)).ToListAsync();
    return rows.GroupBy(x => x.Tier).Select(x => x.First()).OrderBy(x => x.Tier).ToList();
  }
  public static async Task<List<RequestableTier>> Requestable(CentreDb db, string userId, List<MainChoice>? main = null)
  {
    main ??= await MainEntries(db);
    var owned = await db.Grants.Where(x => x.DeletedAt == null && (x.SubjectType == "everyone" || x.SubjectType == "user" && x.SubjectId == userId)).Select(x => x.RightKey).ToListAsync();
    var history = await db.TierRequests.Where(x => x.DeletedAt == null && x.UserId == userId).OrderByDescending(x => x.RequestedAt).ThenByDescending(x => x.Id).ToListAsync();
    var latest = history.GroupBy(x => x.Tier).ToDictionary(x => x.Key, x => x.First());
    return main.Where(x => x.Tier != 99 && !owned.Contains("chat.tier." + x.Tier.ToString(CultureInfo.InvariantCulture))).Select(x =>
    {
      var status = latest.TryGetValue(x.Tier, out var row) && row.Status is "pending" or "rejected" ? row.Status : null;
      return new RequestableTier(x.Tier, x.Title, status);
    }).ToList();
  }
}
