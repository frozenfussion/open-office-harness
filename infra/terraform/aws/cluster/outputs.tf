# SPDX-License-Identifier: AGPL-3.0-only
output "cluster_name" { value = aws_eks_cluster.main.name }
output "endpoint" { value = aws_eks_cluster.main.endpoint }
output "certificate_authority_data" { value = aws_eks_cluster.main.certificate_authority[0].data }
output "vpc_id" { value = aws_vpc.main.id }
output "public_subnet_a_id" { value = aws_subnet.public["a"].id }
output "public_subnet_cidrs" { value = [for subnet in aws_subnet.public : subnet.cidr_block] }
output "private_subnet_a_id" { value = aws_subnet.private["a"].id }
