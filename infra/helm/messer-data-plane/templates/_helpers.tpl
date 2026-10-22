{{/* Chart name, release-scoped names and labels. */}}
{{- define "messer.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "messer.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name (include "messer.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "messer.componentName" -}}
{{- printf "%s-%s" (include "messer.fullname" .root) .component | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "messer.labels" -}}
app.kubernetes.io/name: {{ include "messer.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: messer
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end -}}

{{- define "messer.selectorLabels" -}}
app.kubernetes.io/name: {{ include "messer.name" .root }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{- define "messer.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "messer.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "messer.image" -}}
{{- $tag := default .root.Chart.AppVersion .root.Values.global.imageTag -}}
{{- printf "%s/%s:%s" (trimSuffix "/" .root.Values.global.imageRegistry) .spec.image $tag -}}
{{- end -}}

{{- define "messer.pvcName" -}}
{{- default (printf "%s-data" (include "messer.fullname" .)) .Values.persistence.existingClaim -}}
{{- end -}}
