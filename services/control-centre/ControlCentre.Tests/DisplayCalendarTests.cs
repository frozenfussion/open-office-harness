// SPDX-License-Identifier: AGPL-3.0-only
using ControlCentre.Platform;
using Xunit;
namespace ControlCentre.Tests;

public sealed class DisplayCalendarTests
{
  [Fact]
  public void KualaLumpurDayStartsOnPreviousUtcDateAndRefreshesAtLocalMidnight()
  {
    var calendar = new DisplayCalendar(); var now = DateTimeOffset.Parse("2051-01-02T16:05:00Z"); var (start, end) = calendar.Day(now);
    Assert.Equal(DateTimeOffset.Parse("2051-01-02T16:00:00Z"), start); Assert.Equal(start.AddDays(1), end);
    Assert.True(calendar.RefreshSighting(start.AddMinutes(-5), now)); Assert.False(calendar.RefreshSighting(start.AddMinutes(1), now));
    Assert.True(calendar.RefreshSighting(now.AddHours(-1), now));
  }
  [Fact]
  public void ConfiguredZoneUsesItsOwnDayAndDaylightSavingBoundary()
  {
    var now = DateTimeOffset.Parse("2026-03-08T12:00:00Z");
    var (start, end) = new DisplayCalendar("America/New_York").Day(now);
    Assert.Equal(DateTimeOffset.Parse("2026-03-08T05:00:00Z"), start); Assert.Equal(TimeSpan.FromHours(23), end - start);
    Assert.Equal(DateTimeOffset.Parse("2026-03-08T00:00:00Z"), new DisplayCalendar("UTC").Day(now).Start);
  }
}
