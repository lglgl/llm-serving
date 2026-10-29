{{- define "llm-serving-pilot.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "llm-serving-pilot.fullname" -}}
{{- printf "%s" (include "llm-serving-pilot.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "llm-serving-pilot.labels" -}}
app.kubernetes.io/name: {{ include "llm-serving-pilot.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | quote }}
{{- end -}}
