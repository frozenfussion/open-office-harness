// SPDX-License-Identifier: AGPL-3.0-only
namespace ControlCentre.Platform;

public sealed class DisplayCalendar(string zoneId = "Asia/Kuala_Lumpur")
{
  public TimeZoneInfo Zone { get; } = TimeZoneInfo.FindSystemTimeZoneById(zoneId);
  public (DateTimeOffset Start, DateTimeOffset End) Day(DateTimeOffset now)
  {
    var date = TimeZoneInfo.ConvertTime(now, Zone).Date;
    return (new DateTimeOffset(TimeZoneInfo.ConvertTimeToUtc(date, Zone)), new DateTimeOffset(TimeZoneInfo.ConvertTimeToUtc(date.AddDays(1), Zone)));
  }
  public bool RefreshSighting(DateTimeOffset lastSeen, DateTimeOffset now) => lastSeen <= now.AddHours(-1) || lastSeen < Day(now).Start;
}
