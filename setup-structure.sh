#!/bin/bash

# Root directories
mkdir -p mobile/app/src/main/java/com/civichealth
mkdir -p mobile/app/src/main/res
mkdir -p mobile/app/src/test
mkdir -p mobile/gradle

# Mobile app modules
mkdir -p mobile/app/src/main/java/com/civichealth/citizen
mkdir -p mobile/app/src/main/java/com/civichealth/worker
mkdir -p mobile/app/src/main/java/com/civichealth/official
mkdir -p mobile/app/src/main/java/com/civichealth/shared
mkdir -p mobile/app/src/main/java/com/civichealth/voice
mkdir -p mobile/app/src/main/java/com/civichealth/chatbot
mkdir -p mobile/app/src/main/java/com/civichealth/sync
mkdir -p mobile/app/src/main/java/com/civichealth/blockchain

# Mobile resources
mkdir -p mobile/app/src/main/res/layout
mkdir -p mobile/app/src/main/res/drawable
mkdir -p mobile/app/src/main/res/values

# Backend
mkdir -p backend/src/api/citizen
mkdir -p backend/src/api/worker
mkdir -p backend/src/api/official
mkdir -p backend/src/api/chatbot
mkdir -p backend/src/services/query-tracker
mkdir -p backend/src/services/sla-engine
mkdir -p backend/src/services/anti-gaming
mkdir -p backend/src/services/whatsapp
mkdir -p backend/src/services/idsp-export
mkdir -p backend/src/models
mkdir -p backend/src/middleware
mkdir -p backend/config
mkdir -p backend/tests

# ML Pipeline
mkdir -p ml/data/raw
mkdir -p ml/data/processed
mkdir -p ml/data/synthetic
mkdir -p ml/models/outbreak_predictor
mkdir -p ml/models/retraining
mkdir -p ml/models/evaluation
mkdir -p ml/notebooks
mkdir -p ml/scripts

# Dashboard
mkdir -p dashboard/src/components/WardMap
mkdir -p dashboard/src/components/SLATracker
mkdir -p dashboard/src/components/ResolutionBoard
mkdir -p dashboard/src/components/WeeklyReport
mkdir -p dashboard/src/pages
mkdir -p dashboard/src/utils

# Voice UI
mkdir -p voice-ui/asr
mkdir -p voice-ui/tts
mkdir -p voice-ui/dialects/bhojpuri
mkdir -p voice-ui/dialects/awadhi
mkdir -p voice-ui/dialects/maithili
mkdir -p voice-ui/dialects/hindi
mkdir -p voice-ui/pictograms

# Blockchain
mkdir -p blockchain/contracts
mkdir -p blockchain/scripts
mkdir -p blockchain/tests

# Documentation
mkdir -p docs/api
mkdir -p docs/architecture
mkdir -p docs/ux-research
mkdir -p docs/compliance
mkdir -p docs/deployment

# Scripts and tests
mkdir -p scripts
mkdir -p tests/integration
mkdir -p tests/e2e

echo "Directory structure created successfully!"
