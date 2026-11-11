// SPDX-License-Identifier: AGPL-3.0-only
using System.Text.Json.Nodes;
using ControlCentre.Platform;
using Microsoft.EntityFrameworkCore;

namespace ControlCentre.Registry;

public sealed record RequestableSkill(string Name, string Title, string Description, string? Requested);
public static class SkillChoices
{
  public static async Task<List<RequestableSkill>> Requestable(CentreDb db, string user)
  {
    var grants = await db.Grants.Where(x => x.DeletedAt == null && (x.SubjectType == "everyone" || x.SubjectId == user)).Select(x => x.RightKey).ToListAsync();
    var requests = await db.SkillRequests.Where(x => x.DeletedAt == null && x.UserId == user).OrderByDescending(x => x.RequestedAt).ThenByDescending(x => x.Id).ToListAsync();
    return (await db.Skills.Where(x => x.DeletedAt == null).OrderBy(x => x.Name).ToListAsync())
      .Select(x => (Row: x, Manifest: JsonNode.Parse(x.Manifest)!))
      .Where(x => !grants.Contains(x.Manifest["right"]!.GetValue<string>()))
      .Select(x => new RequestableSkill(x.Row.Name, x.Manifest["title"]!.GetValue<string>(), x.Manifest["description"]!.GetValue<string>(),
        requests.FirstOrDefault(r => r.Skill == x.Row.Name) is { Status: "pending" or "rejected" } r ? r.Status : null)).ToList();
  }
  public static object View(RequestableSkill x) => new JsonObject { ["name"] = x.Name, ["title"] = x.Title, ["description"] = x.Description, ["requested"] = x.Requested };
}
