import { error } from '@sveltejs/kit';
import { isValiError } from 'valibot';
import { ConfigurationError } from '../../configuration.ts';

export async function configurationAction<T>(operation: Promise<T>): Promise<T> {
	try {
		return await operation;
	} catch (failure) {
		if (failure instanceof ConfigurationError || isValiError(failure)) {
			error(400, failure.message);
		}
		throw failure;
	}
}
