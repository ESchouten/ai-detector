import { error } from '@sveltejs/kit';
import { isValiError } from 'valibot';
import { ConfigurationError } from '../../configuration.ts';

export async function configurationAction(operation: Promise<void>): Promise<void> {
	try {
		await operation;
	} catch (failure) {
		if (failure instanceof ConfigurationError || isValiError(failure)) {
			error(400, failure.message);
		}
		throw failure;
	}
}
