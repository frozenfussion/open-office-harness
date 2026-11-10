# SPDX-License-Identifier: AGPL-3.0-only
FROM mcr.microsoft.com/dotnet/sdk:10.0.403-noble AS build
WORKDIR /src
COPY ControlCentre/ControlCentre.csproj ControlCentre/packages.lock.json ControlCentre/
RUN dotnet restore ControlCentre/ControlCentre.csproj --locked-mode
COPY ControlCentre/ ControlCentre/
RUN dotnet publish ControlCentre/ControlCentre.csproj -c Release --no-restore -o /app /p:UseAppHost=false

FROM mcr.microsoft.com/dotnet/aspnet:10.0.14-noble-chiseled
WORKDIR /app
COPY --from=build /app .
USER $APP_UID
ENV ASPNETCORE_HTTP_PORTS="8080;8081"
ENV DOTNET_EnableDiagnostics=0
EXPOSE 8080 8081
ENTRYPOINT ["dotnet", "ControlCentre.dll"]
