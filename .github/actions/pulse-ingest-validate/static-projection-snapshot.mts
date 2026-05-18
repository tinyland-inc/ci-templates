#!/usr/bin/env tsx
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import {
	StaticProjectionSnapshotError,
	validateActivityPubActorKeyDocument,
	validateStaticProjectionSnapshot,
	type JsonValue,
} from '../src/lib/projection/static-snapshot.ts';

type CliOptions = {
	expectedSourceAuthority?: string;
	expectedSpokeTarget?: string;
	actorDocument?: string;
	expectedActorId?: string;
	expectedActorKeyId?: string;
	dryRun: boolean;
};

const MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024;

function usage(): never {
	console.error(`Usage:
  tsx scripts/static-projection-snapshot.mts validate <snapshot.json> [--expected-source-authority tinyland.dev] [--expected-spoke <host>] [--actor-document <actor.json|https-url>] [--expected-actor-id <url>] [--expected-actor-key-id <url#main-key>]
  tsx scripts/static-projection-snapshot.mts sync <source.json|https-url> <target.json> [--expected-source-authority tinyland.dev] [--expected-spoke <host>] [--actor-document <actor.json|https-url>] [--expected-actor-id <url>] [--expected-actor-key-id <url#main-key>] [--dry-run]

This tool validates checked-in static Tinyland projection snapshots. It does not
enable runtime broker fetches, mutation APIs, checkout sessions, or ActivityPub
delivery workers in a generated sister site. Actor document validation checks
public-key publication readiness only; it is not a substitute for a signed
snapshot proof.`);
	process.exit(2);
}

function parseOptions(args: string[]): { positional: string[]; options: CliOptions } {
	const positional: string[] = [];
	const options: CliOptions = { dryRun: false };

	for (let index = 0; index < args.length; index += 1) {
		const arg = args[index];
		if (arg === '--expected-source-authority') {
			options.expectedSourceAuthority = args[index + 1];
			index += 1;
		} else if (arg === '--expected-spoke') {
			options.expectedSpokeTarget = args[index + 1];
			index += 1;
		} else if (arg === '--actor-document') {
			options.actorDocument = args[index + 1];
			index += 1;
		} else if (arg === '--expected-actor-id') {
			options.expectedActorId = args[index + 1];
			index += 1;
		} else if (arg === '--expected-actor-key-id') {
			options.expectedActorKeyId = args[index + 1];
			index += 1;
		} else if (arg === '--dry-run') {
			options.dryRun = true;
		} else if (arg.startsWith('--')) {
			usage();
		} else {
			positional.push(arg);
		}
	}

	if (
		options.expectedSourceAuthority === '' ||
		options.expectedSpokeTarget === '' ||
		options.actorDocument === '' ||
		options.expectedActorId === '' ||
		options.expectedActorKeyId === '' ||
		(options.expectedSourceAuthority === undefined && args.includes('--expected-source-authority')) ||
		(options.expectedSpokeTarget === undefined && args.includes('--expected-spoke')) ||
		(options.actorDocument === undefined && args.includes('--actor-document')) ||
		(options.expectedActorId === undefined && args.includes('--expected-actor-id')) ||
		(options.expectedActorKeyId === undefined && args.includes('--expected-actor-key-id'))
	) {
		usage();
	}

	return { positional, options };
}

function parseJsonSnapshot(raw: string, sourceLabel: string): JsonValue {
	try {
		return JSON.parse(raw) as JsonValue;
	} catch (error) {
		const message = error instanceof Error ? error.message : String(error);
		throw new Error(`${sourceLabel} is not valid JSON: ${message}`);
	}
}

function parseHttpsSource(source: string): URL | undefined {
	try {
		const url = new URL(source);
		if (url.protocol !== 'https:') {
			throw new Error('remote snapshot source must use https');
		}
		if (url.username || url.password || url.search || url.hash) {
			throw new Error('remote snapshot URL must not include credentials, query params, or fragments');
		}
		return url;
	} catch (error) {
		if (source.startsWith('http://') || source.startsWith('https://')) {
			throw error;
		}
		return undefined;
	}
}

async function readSnapshotSource(source: string): Promise<string> {
	const httpsSource = parseHttpsSource(source);
	if (!httpsSource) {
		return readFile(resolve(source), 'utf8');
	}

	const response = await fetch(httpsSource);
	if (!response.ok) {
		throw new Error(`failed to fetch ${httpsSource.href}: HTTP ${response.status}`);
	}

	const lengthHeader = response.headers.get('content-length');
	if (lengthHeader && Number.parseInt(lengthHeader, 10) > MAX_SNAPSHOT_BYTES) {
		throw new Error(`snapshot exceeds ${MAX_SNAPSHOT_BYTES} byte limit`);
	}

	const raw = await response.text();
	if (Buffer.byteLength(raw, 'utf8') > MAX_SNAPSHOT_BYTES) {
		throw new Error(`snapshot exceeds ${MAX_SNAPSHOT_BYTES} byte limit`);
	}

	return raw;
}

function printValidationSummary(command: string, result: ReturnType<typeof validateStaticProjectionSnapshot>): void {
	const projectionKind = result.projectionKind ? ` projectionKind=${result.projectionKind}` : '';
	const sourceAuthority = result.sourceAuthority ? ` sourceAuthority=${result.sourceAuthority}` : '';
	const spokeTarget = result.spokeTarget ? ` spokeTarget=${result.spokeTarget}` : '';
	console.log(
		`${command}: schemaVersion=${result.schemaVersion} itemCount=${result.itemCount}${projectionKind}${sourceAuthority}${spokeTarget}`,
	);
}

async function validateActorDocument(options: CliOptions): Promise<void> {
	if (!options.actorDocument) {
		return;
	}

	const raw = await readSnapshotSource(options.actorDocument);
	const actor = parseJsonSnapshot(raw, options.actorDocument);
	const result = validateActivityPubActorKeyDocument(actor, {
		expectedActorId: options.expectedActorId,
		expectedPublicKeyId: options.expectedActorKeyId,
		expectedPublicKeyOwner: options.expectedActorId,
	});
	console.log(
		`actor-key-ready: actorId=${result.actorId} publicKeyId=${result.publicKeyId} fingerprintSha256=${result.publicKeyFingerprintSha256}`,
	);
}

async function validateCommand(snapshotPath: string, options: CliOptions): Promise<void> {
	const raw = await readSnapshotSource(snapshotPath);
	const snapshot = parseJsonSnapshot(raw, snapshotPath);
	const result = validateStaticProjectionSnapshot(snapshot, options);
	printValidationSummary('validated', result);
	await validateActorDocument(options);
}

async function syncCommand(source: string, target: string, options: CliOptions): Promise<void> {
	if (target.startsWith('http://') || target.startsWith('https://')) {
		throw new Error('target must be a local checked-in JSON file path');
	}

	const raw = await readSnapshotSource(source);
	const snapshot = parseJsonSnapshot(raw, source);
	const result = validateStaticProjectionSnapshot(snapshot, options);
	printValidationSummary(options.dryRun ? 'validated-dry-run' : 'synced', result);
	await validateActorDocument(options);

	if (!options.dryRun) {
		const targetPath = resolve(target);
		await mkdir(dirname(targetPath), { recursive: true });
		await writeFile(targetPath, `${JSON.stringify(snapshot, null, '\t')}\n`);
	}
}

async function main(): Promise<void> {
	const [command, ...rest] = process.argv.slice(2);
	const { positional, options } = parseOptions(rest);

	if (command === 'validate' && positional.length === 1) {
		await validateCommand(positional[0], options);
		return;
	}

	if (command === 'sync' && positional.length === 2) {
		await syncCommand(positional[0], positional[1], options);
		return;
	}

	usage();
}

main().catch((error: unknown) => {
	if (error instanceof StaticProjectionSnapshotError) {
		console.error(error.message);
	} else if (error instanceof Error) {
		console.error(error.message);
	} else {
		console.error(String(error));
	}
	process.exit(1);
});
