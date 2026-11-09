// SPDX-License-Identifier: AGPL-3.0-only
using ControlCentre.Platform;
using Microsoft.EntityFrameworkCore;

namespace ControlCentre.Audit;

public static class AuditRoutes
{
  public static void Map(WebApplication app)
  {
    app.MapGet("/api/admin/audit", async (HttpContext c, CentreDb db) =>
    {
      Api.Authorize(c); Api.Query(c, "actor", "action", "target", "correlation_id", "before_id", "limit");
      var query = db.Audit.AsQueryable();
      if (c.Request.Query.ContainsKey("actor")) { var actor = Api.Q(c, "actor"); query = query.Where(x => x.Actor == actor); }
      if (c.Request.Query.ContainsKey("action")) { var action = Api.Q(c, "action"); query = query.Where(x => x.Action == action); }
      if (c.Request.Query.ContainsKey("target")) { var target = Api.Q(c, "target"); query = query.Where(x => x.Target == target); }
      if (c.Request.Query.ContainsKey("correlation_id")) { var correlation = Api.Id(Api.Q(c, "correlation_id")); query = query.Where(x => x.CorrelationId == correlation); }
      if (c.Request.Query.ContainsKey("before_id"))
      {
        Api.Require(long.TryParse(Api.Q(c, "before_id"), out var id) && id > 0);
        query = query.Where(x => x.Id < id);
      }
      return Results.Ok((await query.OrderByDescending(x => x.Id).Take(Api.Limit(c)).ToListAsync()).Select(row =>
          {
            var value = System.Text.Json.Nodes.JsonNode.Parse(Api.Encode(row))!.AsObject();
            value["detail"] = System.Text.Json.Nodes.JsonNode.Parse(row.Detail);
            return value;
          }));
    }).RequireAuthorization();
  }
}
