import json
import os
import structlog
from typing import Dict, Any, List, Optional

from wire.agents.exploration.crawler import Crawler
from wire.agents.exploration.fuzzer import InteractionFuzzer
from wire.agents.exploration.region_probe import RegionProbe
from wire.agents.observation.browser_session import BrowserSession
from wire.agents.observation.viewport_renderer import ViewportRenderer
from wire.agents.observation.auth_handler import AuthHandler
from wire.agents.observation.shadow_piercer import ShadowPiercer
from wire.agents.observation.spa_detector import SPADetector
from wire.agents.extraction.asset_downloader import AssetDownloader
from wire.agents.extraction.design_analyzer import DesignAnalyzer
from wire.agents.extraction.interaction_recorder import InteractionRecorder
from wire.agents.extraction.legal_detector import LegalDetector
from wire.agents.extraction.network_monitor import NetworkMonitor
from wire.storage.local import LocalStorage
from wire.storage.template_repo import TemplateRepository
from wire.utils.fidelity_scorer import FidelityScorer
from wire.orchestrator.scheduler import TaskScheduler
from wire.orchestrator.coordinator import Coordinator
from wire.orchestrator.checkpointing import CheckpointManager
from wire.orchestrator.semantic_merger import SemanticMerger
from wire.orchestrator.consensus import ConsensusValidator
from wire.schema.canonical import CanonicalDesignSchema, ComponentNode, DesignTokens, HTMLToCidsParser
from wire.schema.style_mapper import CascadeResolver
from wire.schema.input_blueprint import InputBlueprint, DataSlot, SlotConstraint
from wire.compilers.html_compiler import HTMLCompiler
from wire.compilers.react_adapter import ReactAdapter
from wire.compilers.vue_adapter import VueAdapter
from wire.validation.visual_diff import VisualDiff
from wire.validation.structural import StructuralValidator
from wire.synthesis.prompt_generator import PromptGenerator
from wire.synthesis.knowledge_index import KnowledgeIndex
from wire.templates.registry import TemplateRegistry
from wire.templates.tokens import DesignTokenSystem
from wire.templates.artifact import WireArtifact
from wire.templates.composer import TemplateComposer
from wire.templates.versioning import TemplateVersioning
from wire.templates.preview import TemplatePreview
from wire.semantic.llm_guard import LLMGuard
from wire.semantic.section_classifier import SectionClassifier
from wire.semantic.placeholder_detector import PlaceholderDetector
from wire.semantic.form_schema_compiler import FormSchemaCompiler
from wire.semantic.intent_reconciler import IntentReconciler
from wire.semantic.profiles.portfolio_profile import PortfolioProfile
from wire.schema.layout_schema import RemovalPlan, ReflowAction, IntegrityReport, RemovalResult
from wire.layout.section_removal_planner import SectionRemovalPlanner
from wire.layout.layout_reflow_engine import LayoutReflowEngine
from wire.layout.structural_integrity_validator import StructuralIntegrityValidator

logger = structlog.get_logger(__name__)


class ExecutionRouter:
    def __init__(self):
        # Phase 1 — Foundation
        self.crawler = Crawler()
        self.browser = BrowserSession()
        self.downloader = AssetDownloader()
        self.storage = LocalStorage()
        self.scorer = FidelityScorer()

        # Phase 2 — Schema & Design Intelligence
        self.design_analyzer = DesignAnalyzer()
        self.viewport_renderer = ViewportRenderer()
        self.auth_handler = AuthHandler()
        self.scheduler = TaskScheduler()
        self.coordinator = Coordinator()
        self.html_compiler = HTMLCompiler()
        self.react_adapter = ReactAdapter()
        self.vue_adapter = VueAdapter()

        # Phase 3 — Resilience, Validation & Interaction
        self.fuzzer = InteractionFuzzer()
        self.interaction_recorder = InteractionRecorder()
        self.legal_detector = LegalDetector()
        self.visual_diff = VisualDiff()
        self.structural_validator = StructuralValidator()
        self.merger = SemanticMerger()
        self.template_repo = TemplateRepository()
        self.checkpoint: CheckpointManager | None = None

        # Phase 4 — Full-Spectrum & Knowledge Engine
        self.shadow_piercer = ShadowPiercer()
        self.spa_detector = SPADetector()
        self.network_monitor = NetworkMonitor()
        self.prompt_generator = PromptGenerator()
        self.knowledge_index = KnowledgeIndex()

        # Phase 5 — Distributed Scale
        self.region_probe = RegionProbe()
        self.consensus = ConsensusValidator()

        # Phase 6 — Template Ecosystem
        self.template_registry = TemplateRegistry()
        self.token_system = DesignTokenSystem()
        self.artifact_builder = WireArtifact()
        self.composer = TemplateComposer()
        self.versioning = TemplateVersioning()
        self.preview = TemplatePreview()

        # Phase 7 — Semantic Interpretation Layer
        from wire.semantic.llm_client import LLMClient
        self._llm_client = LLMClient()
        self._llm_guard = LLMGuard(llm_client=self._llm_client)
        self._section_classifier = SectionClassifier(self._llm_guard)
        self._placeholder_detector = PlaceholderDetector(self._llm_guard)
        self._form_compiler = FormSchemaCompiler(self._placeholder_detector)
        self._intent_reconciler = IntentReconciler(self._llm_guard)
        self._portfolio_profile = PortfolioProfile()

        # Phase 8 — Layout Adaptation Engine
        self._removal_planner = SectionRemovalPlanner()
        self._reflow_engine = LayoutReflowEngine()
        self._integrity_validator = StructuralIntegrityValidator()

        # Phase 7 config flags
        self.enable_semantic_layer: bool = True
        self.domain_profile: Optional[str] = None
        self.intent_prompt: Optional[str] = None

    async def execute_pipeline(self, url: str) -> float:
        logger.info("executing_full_pipeline", url=url)

        # Initialize storage
        self.storage.initialize_for_url(url)
        self.checkpoint = CheckpointManager(
            os.path.join(self.storage.current_run_dir, ".checkpoint")
        )

        # Resume support
        state = self.checkpoint.load() or {"target_url": url, "completed_pages": []}

        # ── Phase 3: Legal compliance ──
        legal_result = await self.legal_detector.analyze(url)
        self._save_json("compliance_report.json", legal_result)

        # ── Phase 1: Crawl ──
        pages = await self.crawler.crawl(url, single_page=True)

        await self.browser.start()
        partial_results = []
        try:
            for page_url in pages:
                if self.checkpoint.is_page_done(state, page_url):
                    logger.info("skipping_checkpointed_page", url=page_url)
                    continue

                result = await self._process_page(page_url, state)
                partial_results.append(result)
                state = self.checkpoint.mark_page_done(state, page_url)

        except Exception as e:
            self.scorer.log_critical_error("Pipeline execution failed", {"error": str(e)})
            raise
        finally:
            await self.browser.stop()

        # ── Phase 3: Merge results ──
        if partial_results:
            merged = self.merger.merge_page_results(partial_results)
            self._save_json("merged_results.json", merged)

        # ── Phase 3: Template caching ──
        template_id = self.template_repo.store(
            url, self.storage.current_run_dir, {"fidelity": self.scorer.compute_score()}
        )

        # ── Phase 6: Template ecosystem ──
        self._run_template_ecosystem(url, template_id)

        # ── Phase 6: Package .wire artifact ──
        artifact_path = os.path.join(self.storage.current_run_dir, f"{template_id}.wire")
        WireArtifact.package(self.storage.current_run_dir, artifact_path, {"url": url})
        verify_result = WireArtifact.verify(artifact_path)
        self._save_json("artifact_verification.json", verify_result)

        # Clear checkpoint on success
        self.checkpoint.clear()

        score = self.scorer.compute_score()
        logger.info("pipeline_completed_successfully", fidelity_score=score)
        return score

    async def _process_page(self, page_url: str, state: dict) -> dict:
        result: Dict[str, Any] = {"page": page_url, "assets": [], "interactions": [], "errors": []}

        page_lock = f"lock:page:{page_url}"
        if not self.coordinator.acquire_lock(page_lock):
            self.scorer.log_non_critical_error("Lock failed", {"url": page_url})
            return result

        try:
            # ── Phase 1: Capture ──
            content = await self.browser.capture_page(page_url)
            if not content:
                self.scorer.log_critical_error("Failed to capture page content", {"url": page_url})
                return result
            original_content = content

            # ── Phase 1: Extract & download assets ──
            rewritten_content, assets = await self.downloader.download_assets(
                page_url, content, self.storage.get_asset_path()
            )
            self.storage.save_page(page_url, rewritten_content)
            result["assets"] = assets

            # ── Phase 2: Design analysis ──
            css_content_agg = ""
            asset_dir = self.storage.get_asset_path()
            if os.path.exists(asset_dir):
                for root, _, files in os.walk(asset_dir):
                    for fname in files:
                        if fname.endswith(".css"):
                            try:
                                with open(os.path.join(root, fname), "r", encoding="utf-8", errors="ignore") as f:
                                    css_content_agg += "\n" + f.read()
                            except Exception:
                                pass

            design_tokens = self.design_analyzer.extract_design_architecture(rewritten_content, css_content_agg)
            self._save_json("design_architecture.json", design_tokens)

            # Open a live page for interactive work
            page_obj = await self.browser.context.new_page()

            # ── Phase 4: Network monitoring (start before navigation) ──
            self.network_monitor.reset()
            await self.network_monitor.start_monitoring(page_obj)

            await page_obj.goto(page_url, wait_until="networkidle", timeout=30000)

            # ── Phase 4: SPA Detection ──
            spa_result = await self.spa_detector.detect(page_obj)
            self._save_json("spa_detection.json", spa_result)
            if spa_result.get("is_spa"):
                logger.info("spa_detected_triggering_wait_in_router")
                await self.browser.wait_for_dom_stability(page_obj)

            # ── Phase 4: Shadow DOM Piercing ──
            shadow_content = await self.shadow_piercer.extract_shadow_content(page_obj)
            self._save_json("shadow_dom.json", shadow_content)

            # ── Phase 4: Network report ──
            network_report = self.network_monitor.get_report()
            self._save_json("network_report.json", network_report)
            
            # Save API discovery blueprint
            api_endpoints = network_report.get("api_endpoints", [])
            self._save_json("api_discovery_blueprint.json", {
                "url": page_url,
                "api_endpoints_discovered": api_endpoints
            })

            # ── Phase 2: Viewport captures ──
            viewport_results = await self.viewport_renderer.capture_viewports(
                page_obj, self.storage, page_url
            )
            self._save_json("viewports.json", viewport_results)

            # ── Phase 3: Interaction fuzzing ──
            fuzz_results = await self.fuzzer.discover_elements(page_obj)
            self._save_json("interactions_fuzz.json", fuzz_results)

            # ── Phase 3: Interaction recording ──
            hover_records = await self.interaction_recorder.record_hover_states(
                page_obj, fuzz_results.get("hoverable", []), self.storage.get_asset_path()
            )
            result["interactions"] = hover_records
            self._save_json("interaction_catalogue.json", hover_records)

            # ── Phase 5: Multi-region captures ──
            region_results = await self.region_probe.capture_regions(
                self.browser.browser, page_url, self.storage.get_asset_path()
            )
            self._save_json("region_variants.json", region_results)

            # ── Phase 5: Consensus validation (multi-render) ──
            renders = []
            for _ in range(3):
                render_page = await self.browser.context.new_page()
                await render_page.goto(page_url, wait_until="networkidle", timeout=30000)
                render_bytes = await render_page.screenshot(full_page=True)
                renders.append(render_bytes)
                await render_page.close()
            consensus_result = await self.consensus.validate(renders)
            self._save_json("consensus_validation.json", consensus_result)

            await page_obj.close()

            # ── Phase 2.5: Cascade Resolution ──
            resolver = CascadeResolver()
            soup_with_cascade, styles_map = resolver.resolve(rewritten_content, css_content_agg)
            self._save_json("cascade_styles_map.json", {str(k): v for k, v in styles_map.items()})

            # Map captured interactions back to BeautifulSoup node objects
            interactions_map = {}
            if hover_records:
                for rec in hover_records:
                    path = rec.get("unique_path")
                    if path:
                        try:
                            el = soup_with_cascade.select_one(path)
                            if el:
                                interactions_map[id(el)] = {"hover": rec.get("style_diff", {})}
                        except Exception as parse_error:
                            logger.warning("interaction_mapping_failed", path=path, error=str(parse_error))

            # Map shadow DOM structures
            shadow_roots_map = {}
            if shadow_content:
                try:
                    def dict_to_node(d: dict) -> ComponentNode:
                        if not d:
                            return None
                        children = [dict_to_node(c) for c in d.get("children", []) if c]
                        shadow_root = dict_to_node(d["shadow_root"]) if d.get("shadow_root") else None
                        return ComponentNode(
                            tag=d.get("tag", "div"),
                            attributes=d.get("attributes", {}),
                            styles=d.get("styles", {}),
                            children=children,
                            shadow_root=shadow_root,
                            style_provenance=d.get("style_provenance"),
                            text_content=d.get("text_content")
                        )

                    for entry in shadow_content:
                        host_path = entry.get("host_path")
                        shadow_tree_dict = entry.get("shadow_tree")
                        if host_path and shadow_tree_dict:
                            shadow_roots_map[host_path] = dict_to_node(shadow_tree_dict)
                except Exception as shadow_err:
                    logger.warning("shadow_dom_mapping_failed", error=str(shadow_err))

            # ── Phase 2: Schema synthesis (CIDS) ──
            real_root = HTMLToCidsParser.parse(
                soup_with_cascade, 
                styles_map, 
                interactions_map=interactions_map, 
                shadow_roots_map=shadow_roots_map
            )
            cids = CanonicalDesignSchema(
                url=page_url,
                tokens=DesignTokens(**design_tokens),
                root=real_root
            )
            
            # Adaptive node validation
            def get_depth_and_count(node: ComponentNode, current_depth=1):
                if not node.children: return current_depth, 1
                max_d = current_depth
                total_c = 1
                for child in node.children:
                    d, c = get_depth_and_count(child, current_depth + 1)
                    max_d = max(max_d, d)
                    total_c += c
                return max_d, total_c

            cids_depth, cids_count = get_depth_and_count(real_root)
            
            from bs4 import BeautifulSoup
            bs_count = len(BeautifulSoup(rewritten_content, 'lxml').find_all(True))

            logger.info("cids_validation_metrics", 
                        dom_nodes=bs_count,
                        cids_nodes=cids_count, 
                        cids_depth=cids_depth, 
                        css_rules=len(design_tokens.get("colors", {})),
                        elements_styled=len(styles_map),
                        url=page_url)

            if bs_count > 10 and cids_count < bs_count * 0.1:
                raise ValueError(f"CIDS extraction failed proportional consistency check. DOM: {bs_count}, CIDS: {cids_count}")
            if text_val := getattr(real_root, "text_content", None):
                if "Compiled DOM" in text_val:
                    raise ValueError("Mocked 'Compiled DOM' text found in CIDS root.")
            blueprint = InputBlueprint(
                slots={
                    "slot_title": DataSlot(
                        id="slot_title", type="text",
                        constraint=SlotConstraint(allowed_types=["text"])
                    )
                }
            )
            with open(os.path.join(self.storage.current_run_dir, "schema_cids.json"), "w", encoding="utf-8") as f:
                f.write(cids.model_dump_json(indent=2))
            with open(os.path.join(self.storage.current_run_dir, "schema_blueprint.json"), "w", encoding="utf-8") as f:
                f.write(blueprint.model_dump_json(indent=2))

            # ── Phase 5: Framework adapter compilation ──
            react_output = self.react_adapter.compile(cids)
            with open(os.path.join(self.storage.current_run_dir, "output_react.jsx"), "w", encoding="utf-8") as f:
                f.write(react_output)
            vue_output = self.vue_adapter.compile(cids)
            with open(os.path.join(self.storage.current_run_dir, "output_vue.vue"), "w", encoding="utf-8") as f:
                f.write(vue_output)

            # ── Phase 7: Semantic interpretation ──
            if self.enable_semantic_layer:
                self._run_semantic_interpretation(cids, blueprint, page_url)



            # ── Phase 4: AI prompts ──
            prompts = self.prompt_generator.generate_prompts(design_tokens, page_url)
            self._save_json("ai_design_prompts.json", prompts)

            # ── Phase 4: Knowledge index ──
            self.knowledge_index = KnowledgeIndex(self.storage.current_run_dir)
            self.knowledge_index.index_design(page_url, design_tokens)

            # ── Phase 3: Structural validation ──
            structural_result = self.structural_validator.compare(original_content, rewritten_content)
            self._save_json("structural_validation.json", structural_result)

        except Exception as e:
            result["errors"].append(str(e))
            self.scorer.log_non_critical_error("Page processing error", {"url": page_url, "error": str(e)})
        finally:
            self.coordinator.release_lock(page_lock)

        return result

    def _run_template_ecosystem(self, url: str, template_id: str) -> None:
        """Phase 6: Template registry, tokens, versioning, preview."""
        logger.info("running_template_ecosystem", template_id=template_id)

        # Register in registry
        self.template_registry.register(
            template_id, url,
            tags=["auto-extracted", "web-reconstruction"],
            metadata={"source": "wire_pipeline"},
        )

        # Save design tokens
        design_file = os.path.join(self.storage.current_run_dir, "design_architecture.json")
        if os.path.exists(design_file):
            with open(design_file, "r") as f:
                tokens = json.load(f)
            self.token_system.save_tokens(template_id, tokens)

            # Save version
            self.versioning.save_version(template_id, tokens)

            # Generate preview
            preview_html = self.preview.render_preview(
                {"components": [{"id": "root", "tag": "div", "content": f"Preview of {url}"}]},
                tokens,
            )
            preview_path = os.path.join(self.storage.current_run_dir, "preview.html")
            with open(preview_path, "w", encoding="utf-8") as f:
                f.write(preview_html)

    def _run_semantic_interpretation(
        self,
        cids: CanonicalDesignSchema,
        blueprint: InputBlueprint,
        page_url: str,
    ) -> None:
        """Phase 7a: General semantic layer — classify, detect placeholders, compile form schema."""
        logger.info("running_semantic_interpretation", url=page_url)

        # Reset LLM guard call count for this pipeline run
        self._llm_guard.reset_call_count()

        # Step 1: Classify sections
        classifications = self._section_classifier.classify_tree(cids.root)
        self._save_json("section_classifications.json", [
            c.model_dump() for c in classifications
        ])

        # Step 2: Compile form schema (includes placeholder detection per field)
        form_schema = self._form_compiler.compile(
            cids.root, classifications, blueprint, source_url=page_url
        )

        # Step 3: Intent reconciliation (if user provided intent)
        if self.intent_prompt:
            form_schema = self._intent_reconciler.reconcile(
                form_schema, self.intent_prompt
            )

        # Save general form schema
        self._save_json("website_form_schema.json", form_schema.model_dump())
        logger.info(
            "semantic_interpretation_complete",
            sections=len(form_schema.sections),
            fields=len(form_schema.fields),
            needs_confirmation=len(form_schema.needs_confirmation),
        )

        # Phase 7b: Domain profile (optional)
        if self.domain_profile == "portfolio":
            portfolio_schema = self._portfolio_profile.adapt(form_schema)
            self._save_json("portfolio_form_schema.json", portfolio_schema.model_dump())
            logger.info(
                "portfolio_profile_applied",
                mapped=portfolio_schema.mapped_fields,
                excluded=portfolio_schema.excluded_fields,
            )

    def _save_json(self, filename: str, data: Any) -> None:
        filepath = os.path.join(self.storage.current_run_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

    def remove_sections(self, run_id: str, section_node_paths: List[str]) -> RemovalResult:
        """
        Phase 8 layout mutation API.
        Applies section removals, validates mutated tree, and if valid,
        re-compiles React and Vue output files and saves a new template version.
        """
        logger.info("remove_sections_started", run_id=run_id, paths=section_node_paths)

        # 1. Resolve run directory and load CIDS tree
        run_dir = os.path.join(self.storage.base_dir, run_id)
        if not os.path.exists(run_dir):
            raise ValueError(f"Run directory not found: {run_dir}")

        cids_path = os.path.join(run_dir, "schema_cids.json")
        if not os.path.exists(cids_path):
            raise ValueError(f"CIDS schema not found: {cids_path}")

        with open(cids_path, "r", encoding="utf-8") as f:
            cids_data = json.load(f)
        
        cids = CanonicalDesignSchema.model_validate(cids_data)

        plans = []
        current_root = cids.root

        # 2. Sequentially apply removals and planning
        for path in section_node_paths:
            try:
                plan = self._removal_planner.plan(current_root, path)
                mutated_root = self._reflow_engine.execute(current_root, plan)
                
                # Validate the step
                report = self._integrity_validator.validate(current_root, mutated_root, path)
                
                if not report.passed:
                    logger.warning("remove_sections_validation_failed", path=path, violations=len(report.violations))
                    return RemovalResult(
                        mutated_root=mutated_root,
                        plans=plans + [plan],
                        integrity_report=report,
                        recompilation_triggered=False,
                    )
                
                current_root = mutated_root
                plans.append(plan)
            except Exception as e:
                logger.error("remove_sections_error_during_step", path=path, error=str(e))
                # Return report with planning/execution error
                return RemovalResult(
                    mutated_root=current_root,
                    plans=plans,
                    integrity_report=IntegrityReport(
                        passed=False,
                        violations=[IntegrityViolation(
                            node_path=path,
                            rule="planning_or_execution_error",
                            detail=str(e)
                        )]
                    ),
                    recompilation_triggered=False,
                )

        # 3. Validation passed - update CIDS tree root and trigger recompilation
        cids.root = current_root

        # Overwrite schema_cids.json
        with open(cids_path, "w", encoding="utf-8") as f:
            f.write(cids.model_dump_json(indent=2))

        # Re-run Phase 5 compilers
        react_output = self.react_adapter.compile(cids)
        with open(os.path.join(run_dir, "output_react.jsx"), "w", encoding="utf-8") as f:
            f.write(react_output)

        vue_output = self.vue_adapter.compile(cids)
        with open(os.path.join(run_dir, "output_vue.vue"), "w", encoding="utf-8") as f:
            f.write(vue_output)

        # Re-run versioning
        self.versioning.save_version(run_id, cids.model_dump())

        # Build combined final integrity report
        final_report = IntegrityReport(passed=True, violations=[])

        logger.info("remove_sections_completed_successfully", run_id=run_id, plans=len(plans))
        return RemovalResult(
            mutated_root=cids.root,
            plans=plans,
            integrity_report=final_report,
            recompilation_triggered=True,
        )

