# SPDX-License-Identifier: AGPL-3.0-only
resource "helm_release" "traefik" {
  name       = "traefik"
  namespace  = "kube-system"
  repository = "https://traefik.github.io/charts"
  chart      = "traefik"
  version    = "42.4.0"
  timeout    = 600
  values = [yamlencode({
    image             = { tag = "v3.7.18" }
    deployment        = { replicas = 1, podAnnotations = { "prometheus.io/path" = "/metrics", "prometheus.io/port" = "9100", "prometheus.io/scrape" = "true" } }
    ingressClass      = { enabled = true, name = "traefik", isDefaultClass = true }
    providers         = { kubernetesCRD = { enabled = true, allowEmptyServices = true }, kubernetesIngress = { enabled = true, allowEmptyServices = true, publishedService = { enabled = true } } }
    api               = { dashboard = true }
    priorityClassName = "system-cluster-critical"
    tolerations       = [{ key = "CriticalAddonsOnly", operator = "Exists" }, { key = "node-role.kubernetes.io/control-plane", operator = "Exists", effect = "NoSchedule" }]
    ports = {
      traefik   = { port = 8080 }
      metrics   = { port = 9100 }
      web       = { port = 8000, exposedPort = 80, proxyProtocol = { trustedIPs = data.terraform_remote_state.cluster.outputs.public_subnet_cidrs }, transport = { lifeCycle = { requestAcceptGraceTimeout = "0s" } } }
      websecure = { port = 8443, exposedPort = 443, http = { tls = { enabled = true } }, proxyProtocol = { trustedIPs = data.terraform_remote_state.cluster.outputs.public_subnet_cidrs }, transport = { lifeCycle = { requestAcceptGraceTimeout = "0s" } } }
    }
    metrics   = { prometheus = { entryPoint = "metrics" } }
    log       = { level = "INFO" }
    accessLog = { enabled = true, format = "json", fields = { defaultMode = "drop", names = { ClientHost = "keep", DownstreamStatus = "keep", StartUTC = "keep" }, headers = { defaultMode = "drop", names = { X-Ooh-Marker = "keep" } } } }
    service = {
      spec = { type = "LoadBalancer", ipFamilyPolicy = "PreferDualStack" }
      annotations = {
        "service.beta.kubernetes.io/aws-load-balancer-type"            = "external"
        "service.beta.kubernetes.io/aws-load-balancer-scheme"          = "internet-facing"
        "service.beta.kubernetes.io/aws-load-balancer-nlb-target-type" = "ip"
        "service.beta.kubernetes.io/aws-load-balancer-proxy-protocol"  = "*"
        "service.beta.kubernetes.io/aws-load-balancer-subnets"         = data.terraform_remote_state.cluster.outputs.public_subnet_a_id
      }
    }
    resources = { requests = { cpu = "10m", memory = "64Mi" }, limits = { cpu = "200m", memory = "256Mi" } }
  })]
  depends_on = [helm_release.lbc]
}
